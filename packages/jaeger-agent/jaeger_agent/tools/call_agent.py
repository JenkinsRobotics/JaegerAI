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
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jaeger_os.core.tools.tool_registry import register_tool_from_function


def _gateway_base() -> str:
    return (os.environ.get("JAEGER_GATEWAY_URL") or "http://127.0.0.1:8810").rstrip("/")


def _request_json(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 10) -> tuple[int, dict[str, Any]]:
    url = f"{_gateway_base()}{path}"
    raw = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = Request(url, data=raw, method=method)
    req.add_header("Accept", "application/json")
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
    timeout_seconds: int = 120,
    allowed_tools: str = "",
) -> dict[str, Any]:
    """Hand a bounded task to a standing specialist and return its evidence.

    Uses Gateway ``POST /v1/agents/{id}/handoff``. Approval, timeout, cancel
    and specialist failure are explicit. This is not complete until a child
    run result is persisted.
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
                "hint": "Use native:surfaces, native:gateway, or native:everyday",
            }
        target = record.id
    except Exception:
        pass

    rid = (request_id or "").strip() or uuid.uuid4().hex
    tools = [part.strip() for part in str(allowed_tools or "").split(",") if part.strip()]
    status, payload = _request_json(
        "POST",
        f"/v1/agents/{target}/handoff",
        {
            "task": work,
            "from_agent_id": from_agent_id or "native:jaeger",
            "require_approval": bool(require_approval),
            "request_id": rid,
            "parent_run_id": parent_run_id or None,
            "permitted_context": permitted_context,
            "timeout_seconds": int(timeout_seconds),
            "allowed_tools": tools,
        },
        timeout=15,
    )
    if status >= 400 or payload.get("error"):
        return {"ok": False, "status": payload.get("status") or "failed", **payload}
    handoff_id = payload.get("id")
    if payload.get("status") == "pending_approval":
        return {
            "ok": False,
            "status": "pending_approval",
            "error": "Specialist is waiting for an explicit approval decision",
            "handoff": payload,
            "request_id": rid,
        }
    deadline = time.monotonic() + max(1, int(timeout_seconds))
    current = payload
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
