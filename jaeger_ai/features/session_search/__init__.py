"""Session search / FTS helpers for Jaeger ``sessions.db``.

Wraps :class:`jaeger_ai.core.sessions.SessionStore` with safer query
preparation (Hermes FTS sanitizer patterns) and a snippet-aware search
API. Full FTS5 indexing is optional and additive — see ``PORT.md``.
"""

from .query import escape_like, prepare_search_query, sanitize_fts5_query
from .search import SearchHit, search_sessions, search_messages

__all__ = [
    "SearchHit",
    "escape_like",
    "prepare_search_query",
    "sanitize_fts5_query",
    "search_messages",
    "search_sessions",
]
