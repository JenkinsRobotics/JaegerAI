"""SQLite FTS5 Full-Text Search Mixin for JaegerAI Memory.

Adapted from Hermes Agent (`hermes_state_search.py`).
Provides fast BM25 full-text indexing and query capabilities over SQLite
conversation turns and facts in `state.db`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# FTS5 special character sanitizer
_FTS5_SPECIAL_CHARS = '+{}():"^@/#&|~[]<>,;!?$=\\\''
_FTS5_SPECIAL_RE = re.compile(f"[{re.escape(_FTS5_SPECIAL_CHARS)}]")


def sanitize_fts_query(query: str) -> str:
    """Sanitize raw user input string for SQLite FTS5 MATCH queries."""
    if not query:
        return ""
    cleaned = _FTS5_SPECIAL_RE.sub(" ", query)
    tokens = [t.strip() for t in cleaned.split() if t.strip()]
    if not tokens:
        return ""
    # Combine tokens with AND operator for standard search match
    return " AND ".join(f'"{t}"*' for t in tokens)


def _source(conn: sqlite3.Connection) -> tuple[str, str]:
    """Return the source table and its normalized message projection."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episodic'").fetchone():
        return "episodic", (
            "SELECT id * 2 AS rowid, session_key AS session_id, 'user' AS role, "
            "user AS content FROM episodic WHERE user IS NOT NULL UNION ALL "
            "SELECT id * 2 + 1 AS rowid, session_key AS session_id, 'assistant' AS role, "
            "answer AS content FROM episodic WHERE answer IS NOT NULL"
        )
    return "turns", "SELECT rowid, session_id, role, content FROM turns"


def ensure_fts5_schema(conn: sqlite3.Connection) -> bool:
    """Index real conversation storage, including edits and retention deletes.

    The index is derived data. Build once, then maintain it transactionally
    with the source rows. A savepoint avoids committing the caller's writes.
    """
    table, projection = _source(conn)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return False
    conn.execute("SAVEPOINT jaeger_fts_init")
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5("
                     "session_id UNINDEXED, role, content, tokenize='unicode61')")
        marker = f"trg_{table}_ad_fts_v2"
        ready = conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?", (marker,)).fetchone()
        if not ready:
            conn.execute("DROP TRIGGER IF EXISTS trg_turns_ai_fts")
            if table == "episodic":
                insert = (
                    "INSERT INTO turns_fts(rowid, session_id, role, content) "
                    "SELECT new.id*2, new.session_key, 'user', new.user WHERE new.user IS NOT NULL; "
                    "INSERT INTO turns_fts(rowid, session_id, role, content) "
                    "SELECT new.id*2+1, new.session_key, 'assistant', new.answer WHERE new.answer IS NOT NULL;"
                )
                delete = "DELETE FROM turns_fts WHERE rowid IN (old.id*2, old.id*2+1);"
            else:
                insert = ("INSERT INTO turns_fts(rowid, session_id, role, content) "
                          "VALUES(new.rowid, new.session_id, new.role, new.content);")
                delete = "DELETE FROM turns_fts WHERE rowid=old.rowid;"
            for suffix, event, body in (("ai", "INSERT", insert), ("au", "UPDATE", delete+insert), ("ad", "DELETE", delete)):
                conn.execute(f"CREATE TRIGGER trg_{table}_{suffix}_fts_v2 AFTER {event} ON {table} BEGIN {body} END")
            conn.execute("DELETE FROM turns_fts")
            conn.execute("INSERT INTO turns_fts(rowid, session_id, role, content) " + projection)
        conn.execute("RELEASE jaeger_fts_init")
        return True
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK TO jaeger_fts_init")
        conn.execute("RELEASE jaeger_fts_init")
        logger.warning("Full-text index unavailable; using conversation scan: %s", exc)
        return False


class SQLiteSearchEngine:
    """Full-text search engine over SQLite instance store (`state.db`)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.fts_active = ensure_fts5_schema(conn)

    def search_turns(
        self,
        query: str,
        limit: int = 20,
        session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search past message turns using FTS5 BM25 relevance or LIKE fallback."""
        sanitized = sanitize_fts_query(query)
        results: List[Dict[str, Any]] = []

        if self.fts_active and sanitized:
            try:
                if session_id:
                    cursor = self.conn.execute("""
                        SELECT rowid, session_id, role, content, rank
                        FROM turns_fts
                        WHERE turns_fts MATCH ? AND session_id = ?
                        ORDER BY rank
                        LIMIT ?
                    """, (sanitized, session_id, limit))
                else:
                    cursor = self.conn.execute("""
                        SELECT rowid, session_id, role, content, rank
                        FROM turns_fts
                        WHERE turns_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (sanitized, limit))

                for row in cursor.fetchall():
                    results.append({
                        "id": row[0],
                        "session_id": row[1],
                        "role": row[2],
                        "content": row[3],
                        "score": row[4],
                    })
                return results
            except sqlite3.Error as e:
                logger.warning(f"FTS5 MATCH query failed, falling back to LIKE: {e}")

        # Fallback LIKE search if FTS5 not enabled or MATCH fails
        _, projection = _source(self.conn)
        like_pattern = f"%{query}%"
        if session_id:
            cursor = self.conn.execute(f"""
                SELECT rowid, session_id, role, content
                FROM ({projection})
                WHERE content LIKE ? AND session_id = ?
                LIMIT ?
            """, (like_pattern, session_id, limit))
        else:
            cursor = self.conn.execute(f"""
                SELECT rowid, session_id, role, content
                FROM ({projection})
                WHERE content LIKE ?
                LIMIT ?
            """, (like_pattern, limit))

        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "session_id": row[1],
                "role": row[2],
                "content": row[3],
                "score": 0.0,
            })
        return results
