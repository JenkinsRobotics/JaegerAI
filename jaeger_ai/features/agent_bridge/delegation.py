"""Durable origin for bridge handoffs through the existing Gateway team path."""

from jaeger_ai.contract import handoffs

from .service import BridgeError, enabled


def origin(gateway, session_id, request_id):
    """Resolve a root goal or an exactly bound canonical specialist child.

    Session metadata alone is untrusted. A child must match the durable handoff's
    deterministic session/request identities and its host-recorded root goal.
    """
    with gateway.store._get_conn() as conn:
        root = conn.execute(
            "SELECT caller,session,request_id FROM agent_goals WHERE session=? AND request_id=?",
            (session_id, request_id),
        ).fetchone()
    if root is not None:
        return dict(root)
    session = gateway.store.get_session(session_id) or {}
    handoff_id = (session.get("metadata") or {}).get("handoff_id")
    handoff = gateway.store.get_handoff(handoff_id) if handoff_id else None
    binding = ((handoff or {}).get("metadata") or {}).get("bridge_origin")
    if not binding:
        return None
    from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session

    if session_id != specialist_session(
        handoff["to_agent_id"], handoff["request_id"]
    ) or request_id != handoffs.child_request_id(handoff["request_id"]):
        raise PermissionError("Bridge child identity mismatch")
    with gateway.store._get_conn() as conn:
        root = conn.execute(
            "SELECT caller,session,request_id FROM agent_goals WHERE caller=? AND session=? AND request_id=?",
            (binding.get("caller"), binding.get("session"), binding.get("request_id")),
        ).fetchone()
    if root is None:
        raise PermissionError("Bridge origin unavailable")
    return dict(root)


def checked_execution(gateway, binding):
    from jaeger_ai.core.gateway.caller_auth import CALLERS

    from .routes import workspace

    enabled()
    root = gateway.store.get_request(binding["request_id"]) or {}
    execution = root.get("execution") or {}
    spec = CALLERS.get(binding["caller"])
    if (
        spec is None
        or root.get("session_id") != binding["session"]
        or execution.get("caller") != spec.actor
        or root.get("status") in {"cancelling", "cancelled", "failed"}
    ):
        raise PermissionError("Bridge origin is not executable")
    folder = workspace(spec.name, execution.get("workspace"))
    return spec.actor, folder


def prepare_handoff(gateway, actor, body, workspace_folder, tools):
    """Called only by authenticated Gateway admission, never from model flags."""
    from jaeger_ai.core.authority.kernel import is_untrusted_actor

    session = str(body.get("session_id") or "")
    request_id = str(body.get("parent_run_id") or body.get("parent_request_id") or "")
    binding = origin(gateway, session, request_id)
    if binding is None:
        if not actor or not is_untrusted_actor(actor):
            return None, tools
        raise BridgeError("Outside handoff requires an admitted bridge parent", 403)
    try:
        expected_actor, folder = checked_execution(gateway, binding)
    except PermissionError:
        raise BridgeError("Bridge parent is unavailable", 403) from None
    parent = gateway.store.get_request(request_id) or {}
    execution = parent.get("execution") or {}
    grant = execution.get("allowed_tools") or []
    if (
        actor != expected_actor
        or parent.get("status") in {"cancelling", "cancelled", "failed"}
        or execution.get("caller") != actor
        or workspace_folder != folder
        or not ({"call_agent", "run_team"} & set(grant))
        or any(tool not in grant for tool in tools)
    ):
        raise BridgeError("Handoff exceeds bridge parent authority", 403)
    return binding, list(tools or grant)


async def cancel_handoffs(gateway, binding):
    """Cancel only children durably linked to this goal, using canonical cancel."""
    from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session

    from .routes import TurnRequest

    for handoff in gateway.store.list_handoffs():
        if (handoff.get("metadata") or {}).get("bridge_origin") != binding or handoff[
            "status"
        ] in {"completed", "failed", "cancelled", "denied"}:
            continue
        gateway.store.save_handoff({**handoff, "status": "cancelled"})
        gateway._close_pending_approvals(handoff["request_id"])
        child_id = handoffs.child_request_id(handoff["request_id"])
        if gateway.store.get_request(child_id) is not None:
            session = specialist_session(handoff["to_agent_id"], handoff["request_id"])
            await gateway.handle_cancel_turn(
                TurnRequest({}, session, {"request_id": child_id})
            )
