"""Session & Memory Database Portability for JaegerAI.

Adapted from Hermes Agent (`hermes_state_portability.py`).
Provides JSON/JSONL export and import tools for JaegerAI memory and state databases (`state.db`).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def export_session_to_json(conn: sqlite3.Connection, session_id: str) -> str:
    """Export a session's metadata, turns, and facts to a JSON string."""
    export_data: Dict[str, Any] = {
        "version": 1,
        "exported_at": time.time(),
        "session_id": session_id,
        "turns": [],
        "facts": [],
    }

    # Export turns
    try:
        cursor = conn.execute(
            "SELECT role, content, timestamp FROM turns WHERE session_id = ? ORDER BY rowid ASC",
            (session_id,)
        )
        for row in cursor.fetchall():
            export_data["turns"].append({
                "role": row[0],
                "content": row[1],
                "timestamp": row[2],
            })
    except sqlite3.Error as e:
        logger.warning(f"Could not export turns for session {session_id}: {e}")

    # Export facts if facts table exists
    try:
        cursor = conn.execute("SELECT key, value, category FROM facts WHERE session_id = ?", (session_id,))
        for row in cursor.fetchall():
            export_data["facts"].append({
                "key": row[0],
                "value": row[1],
                "category": row[2],
            })
    except sqlite3.Error:
        pass

    return json.dumps(export_data, indent=2)


def import_session_from_json(conn: sqlite3.Connection, json_data: str) -> bool:
    """Import a session's metadata, turns, and facts into state.db."""
    try:
        data = json.loads(json_data)
        session_id = data.get("session_id")
        turns = data.get("turns", [])
        facts = data.get("facts", [])

        if not session_id or not isinstance(turns, list):
            logger.error("Invalid import format: missing session_id or turns list")
            return False

        with conn:
            # Insert turns
            for turn in turns:
                conn.execute(
                    "INSERT INTO turns (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                    (
                        session_id,
                        turn.get("role", "user"),
                        turn.get("content", ""),
                        turn.get("timestamp", time.time()),
                    )
                )

            # Insert facts if any
            for fact in facts:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO facts (key, value, category, session_id) VALUES (?, ?, ?, ?)",
                        (fact.get("key"), fact.get("value"), fact.get("category", "general"), session_id)
                    )
                except sqlite3.Error:
                    pass

        return True
    except Exception as e:
        logger.error(f"Failed to import session JSON: {e}")
        return False
