"""Session search / FTS helpers for Jaeger ``sessions.db``.

Wraps :class:`jaeger_ai.core.sessions.SessionStore` with safer query
preparation (Hermes FTS sanitizer patterns) and a snippet-aware search
API. Full FTS5 indexing is optional and additive — see ``PORT.md``.

Canonical DB path: ``<instance>/memory/sessions.db`` (see ``paths.py``).
"""

from .paths import open_session_store, sessions_db_path
from .query import escape_like, prepare_search_query, sanitize_fts5_query
from .search import SearchHit, search_messages, search_sessions

__all__ = [
    "SearchHit",
    "escape_like",
    "open_session_store",
    "prepare_search_query",
    "sanitize_fts5_query",
    "search_messages",
    "search_sessions",
    "sessions_db_path",
]
