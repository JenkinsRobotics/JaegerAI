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


_SESSION_MANAGE_MAX = 20
_WILDCARD_IDS = frozenset({"*", "all", "everything", "any"})


def session_manage(
    action: str,
    session_ids: list[str],
    *,
    active_session_id: str = "",
) -> dict[str, Any]:
    """Archive, unarchive, or delete explicitly named chat sessions and verify the outcome.

    Never accepts wildcards or blank lists, caps each batch at 20 explicit IDs,
    refuses deleting the active session, and independently verifies each session
    through the Gateway after mutating it.
    """
    act = str(action or "").strip().lower()
    if act not in {"archive", "unarchive", "delete"}:
        return {
            "ok": False,
            "error": f"Unsupported action {action!r}; choose 'archive', 'unarchive', or 'delete'.",
        }
    if not isinstance(session_ids, list) or not session_ids:
        return {"ok": False, "error": "session_ids must be a non-empty list of explicit session IDs."}
    if len(session_ids) > _SESSION_MANAGE_MAX:
        return {"ok": False, "error": f"At most {_SESSION_MANAGE_MAX} explicit sessions per call."}

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in session_ids:
        sid = str(raw or "").strip()
        if not sid or sid.lower() in _WILDCARD_IDS or any(ch in sid for ch in "*?/%"):
            return {"ok": False, "error": f"Invalid or wildcard session_id {raw!r}; provide exact session IDs."}
        if sid not in seen:
            seen.add(sid)
            cleaned.append(sid)

    active_clean = str(active_session_id or "").strip()
    if act == "delete" and active_clean and active_clean in seen:
        return {"ok": False, "error": f"Refused to delete active session {active_clean!r}."}

    from urllib.parse import quote
    from jaeger_ai.core.gateway.client import GatewayUnavailable

    client = _gateway()
    succeeded: list[str] = []
    not_found: list[str] = []
    failed: list[dict[str, str]] = []

    for sid in cleaned:
        encoded = quote(sid, safe="")
        try:
            if act == "delete":
                client._call("DELETE", f"/v1/sessions/{encoded}")
                # Independent verification: deleted session must return 404 on readback
                if _read(sid) is None:
                    succeeded.append(sid)
                else:
                    failed.append({"session_id": sid, "error": "session still exists after DELETE"})
            else:
                want_archived = act == "archive"
                updated = client._call("PATCH", f"/v1/sessions/{encoded}", {"archived": want_archived})
                verified = bool(updated.get("archived")) is want_archived if isinstance(updated, dict) else False
                if verified:
                    succeeded.append(sid)
                else:
                    failed.append({"session_id": sid, "error": f"archived state did not verify as {want_archived}"})
        except GatewayUnavailable as exc:
            msg = str(exc)
            if "HTTP 404" in msg:
                not_found.append(sid)
            else:
                failed.append({"session_id": sid, "error": msg})
        except Exception as exc:  # noqa: BLE001
            failed.append({"session_id": sid, "error": str(exc)})

    return {
        "ok": len(failed) == 0 and len(succeeded) > 0,
        "verified": len(failed) == 0,
        "action": act,
        "succeeded": succeeded,
        "not_found": not_found,
        "failed": failed,
    }
