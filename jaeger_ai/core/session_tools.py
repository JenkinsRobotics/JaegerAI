"""Agent-facing search over JaegerAI's authoritative transcript store."""

from __future__ import annotations

import time
from typing import Any


def _format_ts(value: float | int | str | None) -> str:
    if value is None:
        return "unknown"
    try:
        timestamp = float(value)
        if timestamp > 1e11:
            timestamp /= 1000.0
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _gateway():
    from jaeger_ai.core.gateway.client import GatewayTurnClient

    return GatewayTurnClient(caller="jaegerd")


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": str(row.get("session_id") or row.get("id") or ""),
        "title": str(row.get("title") or row.get("last_message_preview") or "Untitled"),
        "source": "jaeger",
        "created_at": _format_ts(row.get("created_at")),
        "last_active": _format_ts(row.get("last_activity_at") or row.get("updated_at")),
        "message_count": int(row.get("message_count") or 0),
        "execution_state": str(row.get("status") or "idle"),
    }


def _read(session_id: str) -> dict[str, Any] | None:
    from jaeger_ai.core.gateway.client import GatewayUnavailable
    try:
        row = _gateway().get_session(session_id)
    except GatewayUnavailable as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    if not row:
        return None
    messages = [
        {
            "role": item.get("role"),
            "content": item.get("content") or item.get("text"),
            "timestamp": _format_ts(item.get("timestamp") or item.get("created_at")),
            "metadata": item.get("metadata") or item.get("meta") or {},
        }
        for item in (row.get("messages") or row.get("transcript") or [])
    ]
    return {
        **_summary({"session_id": session_id, **row}),
        "model": row.get("model"),
        "provider": row.get("provider"),
        "message_count": len(messages),
        "messages": messages,
    }


def session_search(
    query: str | None = None,
    session_id: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Browse, search, or read Jaeger-owned conversations.

    ARES presentation metadata is deliberately outside this tool. External
    surfaces combine it with these transcripts through the versioned bridge.
    """
    bounded_limit = max(1, min(int(limit), 500))
    requested_id = str(session_id or "").strip()
    if requested_id:
        session = _read(requested_id)
        if session is None:
            return {
                "ok": False,
                "mode": "read",
                "error": f"Session '{requested_id}' not found.",
            }
        return {"ok": True, "mode": "read", "session": session}

    mode = "search" if str(query or "").strip() else "browse"
    # ``source`` is retained as an input compatibility hint, not a store
    # selector. WebUI, CLI, native, bridge and agent are surfaces over the one
    # Gateway-owned session database; treating them as separate transcript
    # stores made an agent asking for ``source='webui'`` report a false zero.
    # Search the authoritative store regardless of which surface the model
    # names.

    from urllib.parse import quote
    client = _gateway()
    needle = str(query or "").strip()
    rows = (client._call("GET", f"/v1/sessions?q={quote(needle)}").get("sessions") or []
            if needle else client.list_sessions())
    sessions = [_summary(row) for row in rows[:bounded_limit]]
    if needle:
        return {
            "ok": True,
            "mode": "search",
            "query": needle,
            "total_matches": len(rows),
            "sessions": sessions,
        }
    return {
        "ok": True,
        "mode": "browse",
        "total_sessions": len(rows),
        "summary": f"Found {len(rows)} Jaeger session(s).",
        "sessions": sessions,
    }


def session_organize(actions_json: str = "", label: str = "Jaeger suggestions") -> dict:
    """Read organization or save a reviewable proposal, never apply it from a model."""
    import json
    import urllib.request
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.gateway.client import gateway_base_url
    url = gateway_base_url() + "/v1/chat-organization"
    headers = {**client_headers("jaegerd"), "Content-Type": "application/json"}
    body = None
    if actions_json:
        actions = json.loads(actions_json)
        if not isinstance(actions, list):
            raise ValueError("actions_json must contain a JSON array")
        body = json.dumps({"action": "propose", "actions": actions, "label": label}).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.load(response)
    if body:
        result["next_step"] = "Saved for owner review in Manage > Suggestions to review. No chats changed."
    return result
