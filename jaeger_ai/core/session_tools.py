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


def session_organize(
    actions_json: str = "",
    label: str = "Jaeger suggestions",
    apply: bool = True,
    undo_operation_id: str = "",
) -> dict[str, Any]:
    """Read, directly organize (in Full Auto), propose, or undo session organization into projects, folders/sections, and topics."""
    import json
    import urllib.error
    import urllib.request
    import uuid
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.gateway.client import gateway_base_url

    url = gateway_base_url() + "/v1/chat-organization"
    headers = {**client_headers("jaegerd"), "Content-Type": "application/json"}

    def _call(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)

    undo_id = str(undo_operation_id or "").strip()
    if undo_id:
        res = _call({"action": "undo", "operation_id": undo_id})
        return {"ok": True, "undone": bool(res.get("undone", True)), "operation_id": undo_id}

    if not actions_json:
        snap = _call(None)
        return {"ok": True, **snap}

    actions = json.loads(actions_json) if isinstance(actions_json, str) else actions_json
    if not isinstance(actions, list) or not actions:
        raise ValueError("actions_json must contain a non-empty JSON array")

    if apply:
        before = _call(None)
        rev = int(before.get("revision", 0))
        op_id = f"org-{uuid.uuid4().hex[:12]}"
        try:
            res = _call({"action": "apply", "revision": rev, "actions": actions, "operation_id": op_id})
            after = _call(None)
            return {
                "ok": True,
                "applied": True,
                "verified": int(after.get("revision", -1)) > rev,
                "undoable": True,
                "operation_id": res.get("operation_id") or op_id,
                "revision": after.get("revision"),
                "groups": after.get("groups") or [],
                "sessions_count": len(after.get("sessions") or []),
            }
        except urllib.error.HTTPError as exc:
            if exc.code != 403:
                raise
            # Fall back cleanly to reviewable proposal when owner has not enabled Full Auto.

    result = _call({"action": "propose", "actions": actions, "label": label})
    result["ok"] = True
    result["applied"] = False
    result["proposed"] = True
    result["next_step"] = "Saved for owner review in Manage > Suggestions to review. Enable Full Auto to apply automatically."
    return result


_SESSION_MANAGE_MAX = 200
_WILDCARD_IDS = frozenset({"*", "all", "everything", "any"})


def session_manage(
    action: str,
    session_ids: list[str] | None = None,
    *,
    active_session_id: str = "",
    keep_session_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Archive, unarchive, delete explicitly named sessions, or delete all old sessions except active/kept ones.

    For ``delete_old``, enumerates all sessions via Gateway, protects ``active_session_id``
    and any ``keep_session_ids``, deletes the remaining sessions one-by-one, and verifies
    404 readback for every deleted session.
    """
    act = str(action or "").strip().lower()
    if act not in {"archive", "unarchive", "delete", "delete_old"}:
        return {
            "ok": False,
            "error": f"Unsupported action {action!r}; choose 'archive', 'unarchive', 'delete', or 'delete_old'.",
        }

    active_clean = str(active_session_id or "").strip()
    keep_set = {str(x).strip() for x in (keep_session_ids or []) if str(x).strip()}
    if active_clean:
        keep_set.add(active_clean)

    from urllib.parse import quote
    from jaeger_ai.core.gateway.client import GatewayUnavailable

    client = _gateway()
    cleaned: list[str] = []
    kept: list[str] = []

    if act == "delete_old":
        all_rows = client.list_sessions()
        if not active_clean:
            try:
                active_info = client._call("GET", "/v1/sessions/active")
                cur_active = str((active_info or {}).get("active_session_id") or "").strip()
                if cur_active:
                    keep_set.add(cur_active)
            except Exception:  # noqa: BLE001
                pass
        for row in all_rows:
            sid = str(row.get("session_id") or row.get("id") or "").strip()
            if not sid:
                continue
            if sid in keep_set:
                kept.append(sid)
            else:
                cleaned.append(sid)
        if not cleaned:
            return {
                "ok": True,
                "verified": True,
                "action": "delete_old",
                "deleted_count": 0,
                "succeeded": [],
                "kept": kept,
                "not_found": [],
                "failed": [],
            }
        effective_act = "delete"
    else:
        if not isinstance(session_ids, list) or not session_ids:
            return {"ok": False, "error": "session_ids must be a non-empty list of explicit session IDs."}
        if len(session_ids) > _SESSION_MANAGE_MAX:
            return {"ok": False, "error": f"At most {_SESSION_MANAGE_MAX} explicit sessions per call."}
        seen: set[str] = set()
        for raw in session_ids:
            sid = str(raw or "").strip()
            if not sid or sid.lower() in _WILDCARD_IDS or any(ch in sid for ch in "*?/%"):
                return {"ok": False, "error": f"Invalid or wildcard session_id {raw!r}; provide exact session IDs."}
            if sid not in seen:
                seen.add(sid)
                cleaned.append(sid)
        if act == "delete" and active_clean and active_clean in seen:
            return {"ok": False, "error": f"Refused to delete active session {active_clean!r}."}
        effective_act = act

    succeeded: list[str] = []
    not_found: list[str] = []
    failed: list[dict[str, str]] = []

    for sid in cleaned:
        encoded = quote(sid, safe="")
        try:
            if effective_act == "delete":
                client._call("DELETE", f"/v1/sessions/{encoded}")
                # Independent verification: deleted session must return 404 on readback
                if _read(sid) is None:
                    succeeded.append(sid)
                else:
                    failed.append({"session_id": sid, "error": "session still exists after DELETE"})
            else:
                want_archived = effective_act == "archive"
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
        "deleted_count": len(succeeded) if effective_act == "delete" else 0,
        "succeeded": succeeded,
        "kept": kept,
        "not_found": not_found,
        "failed": failed,
    }
