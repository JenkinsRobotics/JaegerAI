"""Lead calls a standing specialist via Gateway handoff.

Uses existing Gateway ``POST /v1/agents/{id}/handoff`` and waits for a
durable child result. Registration or HTTP 202 is not success. Relationship
knowledge is never treated as permission to run the specialist.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jaeger_os.core.tools.tool_registry import register_tool_from_function


#: Supplies the Gateway base URL. Like the credential below, the Gateway
#: registers it at startup (``set_gateway_base``) so the port lives in one
#: place (``jaeger_ai/contract/ports.py``); jaeger-agent never imports product
#: code. ``JAEGER_GATEWAY_URL`` still wins when set.
_GATEWAY_BASE: Callable[[], str] | None = None


def set_gateway_base(provider: Callable[[], str] | None) -> None:
    global _GATEWAY_BASE
    _GATEWAY_BASE = provider


def _gateway_base() -> str:
    explicit = (os.environ.get("JAEGER_GATEWAY_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    if _GATEWAY_BASE is not None:
        return str(_GATEWAY_BASE() or "").rstrip("/")
    return ""


#: How long a handoff waits for the owner's approval decision before the
#: tool reports ``pending_approval`` and the turn moves on.
APPROVAL_WAIT_S = 300.0
APPROVAL_POLL_S = 0.5

#: Supplies jaegerd's Gateway caller credential. The Gateway registers it at
#: startup (``set_gateway_auth``); jaeger-agent never imports product code or
#: reads a token store itself. Unregistered = no credential = 401 (fail closed).
_GATEWAY_AUTH: Callable[[], dict[str, str]] | None = None


def set_gateway_auth(provider: Callable[[], dict[str, str]] | None) -> None:
    global _GATEWAY_AUTH
    _GATEWAY_AUTH = provider


def _caller_headers() -> dict[str, str]:
    """jaegerd's credential plus the actor of the turn this tool runs in, so a
    handoff started inside an MCP/A2A turn stays attributed to that caller."""
    if _GATEWAY_AUTH is None:
        return {}
    headers = dict(_GATEWAY_AUTH())
    try:
        from jaeger_agent.tool_executor import active_caller_identity
        actor = str(active_caller_identity() or "").strip()
    except Exception:  # noqa: BLE001 - no bound identity: jaegerd's own actor
        actor = ""
    if actor and headers:
        headers["X-Jaeger-Actor"] = actor
    return headers


def _request_json(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 10) -> tuple[int, dict[str, Any]]:
    base = _gateway_base()
    if not base:
        return 503, {"error": "gateway URL not configured (set JAEGER_GATEWAY_URL)", "http_status": 503}
    url = f"{base}{path}"
    raw = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = Request(url, data=raw, method=method)
    req.add_header("Accept", "application/json")
    for key, value in _caller_headers().items():
        req.add_header(key, value)
    if raw is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return int(resp.status), payload if isinstance(payload, dict) else {"result": payload}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {"error": detail or exc.reason}
        if not isinstance(payload, dict):
            payload = {"error": payload}
        payload.setdefault("http_status", int(exc.code))
        return int(exc.code), payload
    except (OSError, URLError) as exc:
        return 503, {"error": f"gateway unreachable: {exc}", "http_status": 503}


def _handoff_body(target: str, work: str, turn: dict[str, Any], *, from_agent_id: str,
                  require_approval: bool, request_id: str, parent_run_id: str,
                  permitted_context: str, timeout_seconds: int, tools: list[str],
                  project_id: str) -> dict[str, Any]:
    """One handoff request. The parent's project workspace rides along, so a
    child without a project still works in the same root as its parent."""
    execution = turn.get("execution") or {}
    body: dict[str, Any] = {
        "task": work,
        "from_agent_id": from_agent_id or "native:jaeger",
        "require_approval": bool(require_approval),
        "request_id": request_id,
        "parent_run_id": parent_run_id or turn.get("request_id") or None,
        "session_id": turn.get("session_id") or None,
        "permitted_context": permitted_context,
        "timeout_seconds": int(timeout_seconds),
        "allowed_tools": tools,
    }
    if project_id:
        body["project_id"] = project_id.strip()
    elif execution.get("workspace"):
        body["workspace"] = str(execution["workspace"])
    return body


_TERMINAL = {"completed", "failed", "cancelled", "denied", "execution_unknown"}


@register_tool_from_function(name="run_team", side_effect="external")
def run_team(assignments: str, project_id: str = "", timeout_seconds: int = 1800) -> dict[str, Any]:
    """Supervisor fan-out: hand several tasks to specialists at once and WAIT for all.

    ``assignments`` is a JSON list: [{"agent_id": "native:researcher", "task": "..."}, ...].
    All run in parallel (within the project's fan-out limit) in the project root
    when ``project_id`` is given. Returns every specialist's result; each result
    is also posted into this chat. Verify the results before you report."""
    try:
        items = json.loads(assignments) if isinstance(assignments, str) else list(assignments or [])
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"assignments must be a JSON list: {exc}"}
    if not isinstance(items, list) or not items or not all(
            isinstance(i, dict) and i.get("agent_id") and i.get("task") for i in items):
        return {"ok": False, "error": 'assignments must be [{"agent_id": ..., "task": ...}, ...]'}
    from jaeger_agent.task_port import current_task_context
    turn = current_task_context() or {}
    submitted: list[dict[str, Any]] = []
    for item in items:
        rid = uuid.uuid4().hex
        status, payload = _request_json(
            "POST", f"/v1/agents/{str(item['agent_id']).strip()}/handoff",
            _handoff_body(str(item["agent_id"]).strip(), str(item["task"]).strip(), turn,
                          from_agent_id="native:jaeger", require_approval=True, request_id=rid,
                          parent_run_id="", permitted_context=str(item.get("context") or ""),
                          timeout_seconds=int(timeout_seconds), tools=[], project_id=project_id),
            timeout=15)
        submitted.append({"agent_id": item["agent_id"], "status_code": status, "handoff": payload})
    deadline = time.monotonic() + max(1, int(timeout_seconds)) + APPROVAL_WAIT_S
    pending = {s["handoff"].get("id") for s in submitted if s["handoff"].get("id")}
    latest: dict[str, dict[str, Any]] = {s["handoff"]["id"]: s["handoff"] for s in submitted if s["handoff"].get("id")}
    while pending and time.monotonic() < deadline:
        for hid in list(pending):
            _, current = _request_json("GET", f"/v1/handoffs/{hid}", timeout=10)
            if current.get("id"):
                latest[hid] = current
            if str(current.get("status") or "") in _TERMINAL:
                pending.discard(hid)
        if pending:
            time.sleep(1.0)
    results = []
    for s in submitted:
        h = latest.get(s["handoff"].get("id") or "", s["handoff"])
        res = h.get("result") or {}
        results.append({
            "agent_id": s["agent_id"], "handoff_id": h.get("id"), "status": h.get("status") or "rejected",
            "ok": h.get("status") == "completed" and bool(res.get("ok", False)),
            "summary": res.get("summary") or h.get("error") or "",
        })
    return {"ok": all(r["ok"] for r in results), "results": results,
            "still_running": sorted(pending), "project_id": project_id or None}


@register_tool_from_function(name="call_agent", side_effect="external")
def call_agent(
    agent_id: str,
    task: str,
    *,
    require_approval: bool = True,
    from_agent_id: str = "native:jaeger",
    request_id: str = "",
    parent_run_id: str = "",
    permitted_context: str = "",
    timeout_seconds: int = 900,
    allowed_tools: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """Hand a bounded task to a standing specialist and return its evidence.

    Team roles: native:reverse-engineer, native:builder, native:reviewer,
    native:researcher, native:designer. Pass ``project_id`` so the specialist
    works in the project's root; leave ``allowed_tools`` empty to give it its
    standing tools. The result is also posted into this chat as a message.

    Uses Gateway ``POST /v1/agents/{id}/handoff``. Approval, timeout, cancel
    and specialist failure are explicit. This is not complete until a child
    run result is persisted. ``require_approval=False`` is honoured only when
    the owner's autonomy is ``auto``; otherwise the owner approves in the chat,
    and retrying with it off does not skip that.
    """
    target = (agent_id or "").strip()
    work = (task or "").strip()
    if not target:
        return {"ok": False, "error": "agent_id is required"}
    if not work:
        return {"ok": False, "error": "task is required"}

    # Native bridge turns are serialized. Submit durably and yield instead
    # of waiting for a child queued behind this parent. A later turn reads it.
    import sys
    host = sys.modules.get("jaeger_ai.main")
    native_parent = host is not None and getattr(host, "_pipeline", {}).get("client") is not None

    try:
        from jaeger_ai.core.agent_registry import get_default_registry

        record = get_default_registry().get_agent(target)
        if record is None:
            return {
                "ok": False,
                "error": f"unknown agent: {target}",
                "hint": "Use native:reverse-engineer, native:builder, native:reviewer, native:researcher, native:designer, native:surfaces, native:gateway or native:everyday",
            }
        target = record.id
    except Exception:
        pass

    rid = (request_id or "").strip() or uuid.uuid4().hex
    tools = [part.strip() for part in str(allowed_tools or "").split(",") if part.strip()]
    # The Gateway-owned turn this tool runs in, so the handoff (its markers and
    # approval card) belongs to that chat. Set by the host, never by the model.
    from jaeger_agent.task_port import current_task_context
    turn = current_task_context() or {}
    status, payload = _request_json(
        "POST",
        f"/v1/agents/{target}/handoff",
        _handoff_body(target, work, turn, from_agent_id=from_agent_id, require_approval=require_approval,
                      request_id=rid, parent_run_id=parent_run_id, permitted_context=permitted_context,
                      timeout_seconds=timeout_seconds, tools=tools, project_id=project_id),
        timeout=15,
    )
    if status >= 400 or payload.get("error"):
        return {"ok": False, "status": payload.get("status") or "failed", **payload}
    handoff_id = payload.get("id")
    current = payload
    # Keep the turn open while the owner decides on the approval card in the
    # chat, so the lead can relay the specialist's reply in the same turn.
    approval_deadline = time.monotonic() + APPROVAL_WAIT_S
    while current.get("status") == "pending_approval" and time.monotonic() < approval_deadline:
        time.sleep(APPROVAL_POLL_S)
        _, current = _request_json("GET", f"/v1/handoffs/{handoff_id}", timeout=10)
        if current.get("error"):
            return {"ok": False, "status": "failed", **current, "request_id": rid}
    if current.get("status") == "pending_approval":
        return {
            "ok": False,
            "status": "pending_approval",
            "error": "Specialist is waiting for an explicit approval decision",
            "handoff": current,
            "request_id": rid,
        }
    deadline = time.monotonic() + max(1, int(timeout_seconds))
    if native_parent and current.get("status") in {"admitted", "running"}:
        return {"ok": True, "completed": False, "status": current["status"],
                "handoff_id": handoff_id, "request_id": rid,
                "guidance": "Child task accepted. End this turn so it can run. Use get_agent_result on a later turn; do not resubmit or poll in this turn."}
    while time.monotonic() < deadline:
        state = str(current.get("status") or "")
        if state in {"completed", "failed", "cancelled", "denied", "execution_unknown"}:
            result = current.get("result") or {}
            ok = state == "completed" and bool(result.get("ok", True)) and not result.get("stub")
            return {
                "ok": ok,
                "status": state,
                "result": result,
                "handoff": current,
                "request_id": rid,
                "child_run_id": current.get("child_run_id"),
                "error": None if ok else (result.get("summary") or state),
            }
        time.sleep(0.1)
        _, current = _request_json("GET", f"/v1/handoffs/{handoff_id}", timeout=10)
        if current.get("error"):
            return {"ok": False, "status": "failed", **current, "request_id": rid}
    return {
        "ok": False,
        "status": "timeout",
        "error": "Specialist did not finish before timeout; not treating as complete",
        "handoff": current,
        "request_id": rid,
    }


@register_tool_from_function(name="get_agent_result", side_effect="read")
def get_agent_result(handoff_id: str) -> dict[str, Any]:
    """Read a durable specialist result once; never starts or retries work."""
    import re
    if not re.fullmatch(r"handoff_[a-zA-Z0-9_-]+", handoff_id):
        return {"ok": False, "error": "Invalid handoff_id"}
    status, payload = _request_json("GET", f"/v1/handoffs/{handoff_id}")
    if status >= 400 or payload.get("error"):
        return {"ok": False, **payload}
    done = payload.get("status") == "completed" and payload.get("result", {}).get("ok") is True
    return {"ok": done, "completed": done, "handoff": payload,
            "status": payload.get("status"), "result": payload.get("result", {})}
