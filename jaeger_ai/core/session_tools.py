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


def _store():
    from jaeger_ai.core.sessions import get_store

    return get_store()


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": str(row.get("id") or ""),
        "title": str(row.get("title") or row.get("preview") or "Untitled"),
        "source": "jaeger",
        "created_at": _format_ts(row.get("created_at")),
        "last_active": _format_ts(row.get("last_active")),
        "message_count": int(row.get("messages") or 0),
        "execution_state": str(row.get("execution_state") or "idle"),
    }


def _read(session_id: str) -> dict[str, Any] | None:
    store = _store()
    if store is None or not store.exists(session_id):
        return None
    rows = {str(row.get("id")): row for row in store.list_sessions(limit=100_000)}
    row = rows.get(session_id, {})
    brain = store.brain(session_id)
    messages = [
        {
            "role": item.get("role"),
            "content": item.get("text"),
            "timestamp": _format_ts(item.get("ts")),
            "metadata": item.get("metadata") or {},
        }
        for item in store.history(session_id)
    ]
    return {
        **_summary({"id": session_id, **row}),
        "model": brain.get("model"),
        "provider": brain.get("provider"),
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

    requested_source = str(source or "").strip().lower()
    mode = "search" if str(query or "").strip() else "browse"
    if requested_source and requested_source not in {"jaeger", "runtime"}:
        return {
            "ok": True,
            "mode": mode,
            "total_sessions": 0,
            "total_matches": 0,
            "sessions": [],
        }

    store = _store()
    if store is None:
        return {
            "ok": True,
            "mode": mode,
            "total_sessions": 0,
            "total_matches": 0,
            "sessions": [],
        }

    needle = str(query or "").strip()
    rows = (
        store.search(needle, limit=bounded_limit)
        if needle
        else store.list_sessions(limit=bounded_limit)
    )
    sessions = [_summary(row) for row in rows]
    if needle:
        return {
            "ok": True,
            "mode": "search",
            "query": needle,
            "total_matches": len(sessions),
            "sessions": sessions,
        }
    return {
        "ok": True,
        "mode": "browse",
        "total_sessions": len(sessions),
        "summary": f"Found {len(sessions)} Jaeger session(s).",
        "sessions": sessions,
    }
