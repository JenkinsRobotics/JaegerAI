"""Truthful bridge projection; only the canonical owner verifies completion."""

from jaeger_ai.core.redaction import redact_text


def project_goal(goal_id, thread, receipt=None, *, gateway=None):
    from .tool_scope import supported_tools

    receipt = receipt or {}
    raw_status = receipt.get("status", "not_admitted")
    result = receipt.get("result") or {}
    output = result.get("output", result.get("text", receipt.get("output", "")))
    verified = False
    # Never accept worker/model task_state or receipt fields as evidence. Read
    # the owner's durable task, bound to this exact admission and session.
    task_id = result.get("task_id")
    if gateway is not None and isinstance(task_id, str):
        task = gateway.task_owner.store.get_task(task_id)
        verified = bool(
            task
            and receipt.get("request_id")
            and receipt.get("session_id")
            and task.state.value == "completed_verified"
            and task.provenance.get("request_id") == receipt.get("request_id")
            and task.provenance.get("session_id") == receipt.get("session_id")
            and task.provenance.get("turn_owned") is True
        )
    return {
        "id": goal_id,
        "thread": thread,
        "execution_mode": "policy_controlled_tools",
        "supported_tools": supported_tools(),
        "execution_verified": verified,
        "status": ("completed_verified" if verified else "completed_unverified")
        if raw_status == "completed"
        else raw_status,
        "request_status": raw_status,
        "result": {"output": redact_text(output) if isinstance(output, str) else ""},
    }
