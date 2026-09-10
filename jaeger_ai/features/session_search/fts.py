"""Optional FTS5 schema helpers for sessions.db (not applied by default).

Donor reference: hermes-agent ``hermes_state_common.FTS_SQL``. Jaeger keeps
plain ``messages`` / ``sessions`` tables authoritative; enabling FTS is a
follow-up migration owned by this feature.
"""

from __future__ import annotations

# Intentionally minimal — do not CREATE VIRTUAL TABLE on import.
MESSAGES_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    session_id UNINDEXED,
    role UNINDEXED,
    content='messages',
    content_rowid='id'
);
"""


def fts_enabled(conn: object) -> bool:
    """Return True when ``messages_fts`` exists on this connection."""
    try:
        row = conn.execute(  # type: ignore[attr-defined]
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        ).fetchone()
    except Exception:  # noqa: BLE001
        return False
    return row is not None
