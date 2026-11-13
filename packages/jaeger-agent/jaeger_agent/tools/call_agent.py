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

APPROVAL_POLL_S = 0.5
APPROVAL_WAIT_S = 300
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from jaeger_os.core.tools.tool_registry import register_tool_from_function


#: The host supplies its bound Gateway URL; jaeger-agent cannot import the
#: product's port contract without making the standalone package depend on it.
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


def _handoff_body(work, turn, *, from_agent_id, require_approval, request_id,
                  parent_run_id, permitted_context, timeout_seconds, tools,
                  project_id=""):
    execution = turn.get("execution") or {}
    body = {
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
    try:  # the asking tool call, so the Process view nests the agent under it
        from jaeger_agent import live as _live
        call_id = _live.current_tool_call()
    except Exception:  # noqa: BLE001
        call_id = None
    if call_id:
        body["call_id"] = str(call_id)
    if project_id:
        body["project_id"] = project_id
    elif execution.get("workspace"):
        body["workspace"] = str(execution["workspace"])
    return body


def _agent_by_name(registry: Any, name: str) -> Any:
    """Resolve ``@Display Name`` / ``Display Name`` / bare name to one agent (exact, case-insensitive)."""
    needle = name.strip().lstrip("@").strip().lower()
    if not needle:
        return None
    try:
        agents = registry.list_agents()
    except Exception:  # noqa: BLE001
        return None
    hits = [a for a in agents if needle in {str(getattr(a, "display_name", "") or "").lower(),
                                            str(getattr(a, "name", "") or "").lower()}]
    return hits[0] if len(hits) == 1 else None


@register_tool_from_function(name="run_team", side_effect="external")
def run_team(assignments: str, project_id: str = "", timeout_seconds: int = 1800) -> dict[str, Any]:
    """Submit bounded specialist tasks and collect each durable result."""
    try:
        items = json.loads(assignments) if isinstance(assignments, str) else list(assignments or [])
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"assignments must be a JSON list: {exc}"}
    if not isinstance(items, list) or not items or not all(
        isinstance(item, dict) and item.get("agent_id") and item.get("task") for item in items
    ):
        return {"ok": False, "error": 'assignments must be [{"agent_id": ..., "task": ...}, ...]'}
    from jaeger_agent.task_port import current_task_context
    turn = current_task_context() or {}
    submitted = []
    for item in items:
        target = str(item["agent_id"]).strip()
        rid = uuid.uuid4().hex
        status, payload = _request_json(
            "POST", f"/v1/agents/{quote(target, safe=':')}/handoff",
            _handoff_body(str(item["task"]).strip(), turn,
                          from_agent_id="native:jaeger", require_approval=True,
                          request_id=rid, parent_run_id="",
                          permitted_context=str(item.get("context") or ""),
                          timeout_seconds=timeout_seconds, tools=[], project_id=project_id),
            timeout=15,
        )
        submitted.append({"agent_id": target, "status_code": status, "handoff": payload})
    latest = {s["handoff"]["id"]: s["handoff"] for s in submitted if s["handoff"].get("id")}
    pending = set(latest)
    deadline = time.monotonic() + max(1, int(timeout_seconds)) + APPROVAL_WAIT_S
    while pending and time.monotonic() < deadline:
        for hid in list(pending):
            _, current = _request_json("GET", f"/v1/handoffs/{hid}", timeout=10)
            if current.get("error"):
                latest[hid] = {"id": hid, "status": "failed", "result": current}
                pending.discard(hid)
            else:
                latest[hid] = current
                if current.get("status") in {"completed", "failed", "cancelled", "denied", "execution_unknown"}:
                    pending.discard(hid)
        if pending:
            time.sleep(APPROVAL_POLL_S)
    results = []
    for item in submitted:
        handoff = latest.get(item["handoff"].get("id"), item["handoff"])
        result = handoff.get("result") or {}
        results.append({
            "agent_id": item["agent_id"], "handoff_id": handoff.get("id"),
            "status": handoff.get("status") or "rejected",
            "ok": handoff.get("status") == "completed" and bool(result.get("ok", False)),
            "summary": result.get("summary") or handoff.get("error") or "",
        })
    return {"ok": all(result["ok"] for result in results), "results": results,
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
    timeout_seconds: int = 120,
    allowed_tools: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """Hand a bounded task to a teammate agent and return its evidence.

    ``agent_id`` is the agent's id (``native:...``) or its display name
    (``@Jaeger Design & Style`` works). Uses Gateway ``POST /v1/agents/{id}/handoff``. Approval, timeout, cancel
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
        from jaeger_agent.core.host import service
        get_default_registry = service("agent_registry").get_default_registry

        registry = get_default_registry()
        record = registry.get_agent(target) or _agent_by_name(registry, target)
        if record is None:
            return {
                "ok": False,
                "error": f"unknown agent: {target}",
                "hint": "Use an agent id (native:...) or its display name; '@Name' works too",
            }
        target = record.id
    except Exception:
        pass

    rid = (request_id or "").strip() or uuid.uuid4().hex
    tools = [part.strip() for part in str(allowed_tools or "").split(",") if part.strip()]
    from jaeger_agent.task_port import current_task_context
    turn = current_task_context() or {}
    body = _handoff_body(work, turn, from_agent_id=from_agent_id,
                         require_approval=require_approval, request_id=rid,
                         parent_run_id=parent_run_id, permitted_context=permitted_context,
                         timeout_seconds=timeout_seconds, tools=tools, project_id=project_id)
    # The Gateway applies the owner's collaboration mode: in one mind (and in
    # auto unless the owner @mentioned the agent) this runs as ``delegate``.
    body["via"] = "call_agent"
    body["lead_allowed_tools"] = _lead_tools()
    status, payload = _request_json(
        "POST", f"/v1/agents/{quote(target, safe=':')}/handoff", body, timeout=15,
    )
    if status >= 400 or payload.get("error"):
        return {"ok": False, "status": payload.get("status") or "failed", **payload}
    handoff_id = payload.get("id")
    current = payload
    if current.get("status") == "pending_approval" and turn:
        approval_deadline = time.monotonic() + APPROVAL_WAIT_S
        while current.get("status") == "pending_approval" and time.monotonic() < approval_deadline:
            time.sleep(APPROVAL_POLL_S)
            _, current = _request_json("GET", f"/v1/handoffs/{handoff_id}", timeout=10)
            if current.get("error"):
                return {"ok": False, "status": "failed", **current, "request_id": rid}
    if current.get("status") == "pending_approval":
        return {"ok": False, "status": "pending_approval",
                "error": "Specialist is waiting for an explicit approval decision",
                "handoff": current, "request_id": rid}
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
    # Only what the lead needs: the record's bookkeeping (tool grants, parent
    # bindings, model choice) is large and stays on the Gateway.
    handoff = {k: payload.get(k) for k in ("id", "status", "from_agent_id", "to_agent_id", "task",
                                           "created_at", "updated_at") if k in payload}
    meta = payload.get("metadata") or {}
    if meta.get("collaboration") == "delegate":
        handoff["kind"] = "delegate"
    return {"ok": done, "completed": done, "handoff": handoff,
            "status": payload.get("status"), "result": payload.get("result", {})}


# ── delegate: think with an inner helper (one-mind collaboration) ──────────
#
# Contract after Hermes Agent's ``delegate_task`` (MIT, NousResearch/hermes-agent
# tools/delegate_tool.py; contract only, no code copied): the helper starts in a
# fresh context from the brief (+ a read-only excerpt of the lead's memory),
# its tools are the lead's narrowed by the helper profile and never wider, it
# cannot message the person, write long-term memory, schedule, delegate further
# or approve itself, and only its result comes back. The Gateway enforces all of
# this (``mode: "delegate"``); this tool only asks and waits.


def _lead_tools() -> list[str] | None:
    """The tools this turn may use (None = the owner's whole catalog)."""
    try:
        from jaeger_agent.tool_executor import active_tool_allowlist
        allowed = active_tool_allowlist()
    except Exception:  # noqa: BLE001
        return None
    return sorted(allowed) if allowed is not None else None


def _lead_workspace(turn: dict[str, Any]) -> str:
    execution = turn.get("execution") or {}
    if execution.get("workspace"):
        return str(execution["workspace"])
    try:
        from jaeger_agent.core.workspace import get_effective_workspace_dir
        return str(get_effective_workspace_dir() or "")
    except Exception:  # noqa: BLE001
        return ""


def _helpers() -> list[dict[str, Any]]:
    _, snap = _request_json("GET", "/v1/team", timeout=10)
    out = []
    for agent in snap.get("agents") or []:
        if agent.get("role") == "lead":
            continue
        out.append({"profile": agent.get("display_name"), "id": agent.get("id"),
                    "does": (agent.get("description") or "")[:200], "skills": agent.get("skills") or []})
    return out


def _resolve_helper(profile: str) -> Any:
    try:
        from jaeger_agent.core.host import service
        registry = service("agent_registry").get_default_registry()
    except Exception:  # noqa: BLE001
        return None
    record = registry.get_agent(profile) or _agent_by_name(registry, profile)
    if record is not None:
        return record
    needle = profile.strip().lstrip("@").strip().lower()
    if len(needle) < 3:
        return None
    try:
        agents = [a for a in registry.list_agents() if not getattr(a, "disabled", False)]
    except Exception:  # noqa: BLE001
        return None
    hits = [a for a in agents if needle in str(getattr(a, "display_name", "") or "").lower()]
    return hits[0] if len(hits) == 1 else None


@register_tool_from_function(name="delegate", side_effect="external")
def delegate(profile: str = "", brief: str = "", context: str = "", timeout_seconds: int = 300) -> dict[str, Any]:
    """Think with one of your inner helpers (Design & Style, Mac App, Gateway & WebUI,
    System Engineer, ...). The helper works on ``brief`` in a fresh context and
    returns only its result to you; it never talks to the person. You then answer
    in your own voice. Use for a focused review or a context-heavy side task;
    for simple things just do the work yourself. Call with no profile to list
    helpers. ``context``: anything from this chat the helper needs (it cannot see
    the chat). Long results come back as a preview plus ``result_path`` to read."""
    work = (brief or "").strip()
    who = (profile or "").strip()
    if not who or who.lower() in {"list", "?", "help"}:
        return {"ok": True, "helpers": _helpers(),
                "guidance": "Call delegate(profile=<profile>, brief=<what you need back>)."}
    if not work:
        return {"ok": False, "error": "brief is required: say exactly what you need back"}
    record = _resolve_helper(who)
    if record is None:
        return {"ok": False, "error": f"unknown helper: {who}", "helpers": _helpers()}
    from jaeger_agent.task_port import current_task_context
    turn = current_task_context() or {}
    rid = uuid.uuid4().hex
    body = _handoff_body(work, turn, from_agent_id="native:jaeger", require_approval=False,
                         request_id=rid, parent_run_id="", permitted_context="",
                         timeout_seconds=max(30, min(int(timeout_seconds or 300), 1800)), tools=[])
    body.update({"mode": "delegate", "context": (context or "").strip()[:8000],
                 "lead_allowed_tools": _lead_tools()})
    workspace = _lead_workspace(turn)
    if workspace and not body.get("project_id"):
        body["workspace"] = workspace
    status, payload = _request_json("POST", f"/v1/agents/{quote(record.id, safe=':')}/handoff", body, timeout=15)
    if status >= 400 or payload.get("error"):
        return {"ok": False, "status": payload.get("status") or "rejected",
                "error": payload.get("error") or f"helper not started (HTTP {status})"}
    handoff_id = payload.get("id")
    current = payload
    deadline = time.monotonic() + int(body["timeout_seconds"]) + 30
    while time.monotonic() < deadline:
        state = str(current.get("status") or "")
        if state in {"completed", "failed", "cancelled", "denied", "execution_unknown"}:
            result = current.get("result") or {}
            meta = result.get("metadata") or {}
            text = str(result.get("summary") or "")
            path = meta.get("result_path")
            out = {"ok": state == "completed", "status": state, "helper": getattr(record, "display_name", record.id),
                   "handoff_id": handoff_id, "result": text[:6000] if path else text,
                   "tokens": meta.get("tokens")}
            if path:
                out["result_path"] = path
                out["note"] = "Result was long; the full text is at result_path (read_file)."
            if state != "completed":
                out["error"] = text or state
            out["answer_in_your_own_voice"] = True
            return out
        time.sleep(0.25)
        _, current = _request_json("GET", f"/v1/handoffs/{handoff_id}", timeout=10)
        if current.get("error"):
            return {"ok": False, "status": "failed", "error": current.get("error"), "handoff_id": handoff_id}
    return {"ok": False, "status": "timeout", "handoff_id": handoff_id,
            "error": "Helper did not finish in time; its result is not treated as done"}
