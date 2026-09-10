"""Search helpers over :class:`~jaeger_ai.core.sessions.SessionStore`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .query import escape_like, prepare_search_query


class _SessionStoreLike(Protocol):
    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]: ...
    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class SearchHit:
    session_id: str
    role: str | None = None
    snippet: str | None = None
    title: str | None = None
    preview: str | None = None
    ts: float | None = None
    message_id: str | None = None


def search_sessions(
    store: _SessionStoreLike,
    query: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Session-level search with sanitized query prep."""
    needle = prepare_search_query(query)
    if not needle:
        return store.list_sessions(limit=limit)
    return store.search(needle, limit=limit)


def search_messages(
    store: Any,
    query: str,
    *,
    limit: int = 50,
    snippet_chars: int = 160,
) -> list[SearchHit]:
    """Message-level LIKE search with short snippets.

    Uses the store's SQLite connection when available so we can return
    role/text/ts without requiring FTS5. Falls back to session-level hits
    when the connection is not exposed.
    """
    needle = prepare_search_query(query)
    if not needle:
        return [
            SearchHit(
                session_id=str(row.get("id") or ""),
                title=row.get("title"),
                preview=row.get("preview"),
            )
            for row in store.list_sessions(limit=limit)
            if row.get("id")
        ]

    conn = getattr(store, "_conn", None)
    lock = getattr(store, "_lock", None)
    if conn is None:
        return [
            SearchHit(
                session_id=str(row.get("id") or ""),
                title=row.get("title"),
                preview=row.get("preview"),
            )
            for row in store.search(needle, limit=limit)
            if row.get("id")
        ]

    pattern = f"%{escape_like(needle)}%"
    sql = (
        "SELECT m.id, m.session_id, m.role, m.text, m.ts, s.title, s.preview "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE m.text LIKE ? ESCAPE '\\' "
        "OR s.title LIKE ? ESCAPE '\\' OR s.preview LIKE ? ESCAPE '\\' "
        "ORDER BY m.ts DESC LIMIT ?"
    )
    args = (pattern, pattern, pattern, max(1, min(int(limit), 500)))

    def _run() -> list[SearchHit]:
        cur = conn.execute(sql, args)
        hits: list[SearchHit] = []
        for mid, sid, role, text, ts, title, preview in cur.fetchall():
            body = str(text or "")
            snippet = body if len(body) <= snippet_chars else body[: snippet_chars - 1] + "…"
            hits.append(
                SearchHit(
                    session_id=str(sid),
                    role=str(role) if role else None,
                    snippet=snippet,
                    title=title,
                    preview=preview,
                    ts=float(ts) if ts is not None else None,
                    message_id=str(mid),
                )
            )
        return hits

    if lock is not None:
        with lock:
            return _run()
    return _run()
