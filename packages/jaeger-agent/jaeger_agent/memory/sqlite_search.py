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


def ensure_fts5_schema(conn: sqlite3.Connection) -> bool:
    """Initialize SQLite FTS5 virtual table and triggers on state.db if supported."""
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
                session_id UNINDEXED,
                role,
                content,
                tokenize='unicode61'
            );
        """)
        # Triggers to keep FTS table in sync with primary turns table if present
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_turns_ai_fts AFTER INSERT ON turns BEGIN
                INSERT INTO turns_fts(rowid, session_id, role, content)
                VALUES (new.rowid, new.session_id, new.role, new.content);
            END;
        """)
        # Populate FTS index from existing turns if any exist
        try:
            conn.execute("""
                INSERT OR IGNORE INTO turns_fts(rowid, session_id, role, content)
                SELECT rowid, session_id, role, content FROM turns;
            """)
        except sqlite3.Error:
            pass
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.warning(f"FTS5 initialization notice (may not be supported in host sqlite): {e}")
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
        like_pattern = f"%{query}%"
        if session_id:
            cursor = self.conn.execute("""
                SELECT rowid, session_id, role, content
                FROM turns
                WHERE content LIKE ? AND session_id = ?
                LIMIT ?
            """, (like_pattern, session_id, limit))
        else:
            cursor = self.conn.execute("""
                SELECT rowid, session_id, role, content
                FROM turns
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
