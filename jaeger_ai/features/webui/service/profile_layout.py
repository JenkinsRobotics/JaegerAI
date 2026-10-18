"""WebUI profile display helpers and agent-home schema.

Single conversation library (Grok-Bot model): one SI/home chat plus
specialist threads labeled by profile/role badges — not a second empty UI
per profile. The vendor WebUI on :8790 uses a Jaeger-owned agent home
(``<state>/webui-agent``); this module only ensures its ``state.db`` has
the ``source`` column the sidebar listing requires. It never links, writes
or reads the legacy ``~/.hermes`` / ``hermes-webui-agent`` homes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from jaeger_ai.contract.frameworks import display_name, is_known

from ..adapter.profile_catalog import PROFILES

# Canonical id → chat/profile label (matches vendor static FALLBACK maps).
PROFILE_DISPLAY_NAMES: dict[str, str] = {name: label for name, _, label in PROFILES}


def profile_display_name(profile_id: str | None) -> str:
    """The friendly label for any spelling of a framework name.

    Accepts a profile ("default"), a runtime ("hermes") or an agent id
    ("tp:hermes") — the contract resolves all three. Before it did, passing a
    runtime fell through to the title-case fallback below and returned
    "Hermes" instead of "Hermes Agent", which is why callers grew their own
    alias maps to work around it.

    The fallback stays for ids that are genuinely not frameworks, such as an
    operator-created profile.
    """
    key = str(profile_id or "default").strip().lower() or "default"
    if is_known(key):
        return display_name(key)
    return key[:1].upper() + key[1:] if key else PROFILE_DISPLAY_NAMES["default"]


def library_model() -> dict[str, Any]:
    """One conversation library with profile/role badges — no empty second UI per profile.

    Includes the AgentRegistry support model so WebUI can list/switch both
    Jaeger-native agents and third-party adapter faces remotely.
    """
    badges = [
        PROFILE_DISPLAY_NAMES["default"],
        PROFILE_DISPLAY_NAMES["jaeger"],
        PROFILE_DISPLAY_NAMES["openclaw"],
        PROFILE_DISPLAY_NAMES["roundtable"],
        "ARES",
    ]
    catalog: dict[str, Any] = {}
    try:
        from jaeger_ai.core.agent_registry import AgentRegistry

        catalog = AgentRegistry().to_catalog()
    except Exception:  # noqa: BLE001 — layout helpers must stay best-effort
        catalog = {
            "jaeger_native": [],
            "third_party": [],
            "fundamentals_fee_gated": False,
        }
    return {
        "mode": "single_library",
        "empty_profile_uis": False,
        "badges": badges,
        "support_model": {
            "jaeger_native": True,
            "third_party": True,
            "fundamentals_fee_gated": False,
        },
        "agents": catalog,
    }


def ensure_agent_state_schema(agent_home: Path) -> dict[str, Any]:
    """Guarantee ``state.db`` exists with a ``source`` column.

    ``jaeger_ai/features/webui/api/agent_sessions.py`` returns an empty list when
    the column is missing, which is the empty-sidebar failure on :8790.
    This does not import live Hermes history — that is the Phase 1 catalog
    import.
    """
    agent_home = agent_home.expanduser()
    agent_home.mkdir(parents=True, exist_ok=True)
    db = agent_home / "state.db"
    conn = sqlite3.connect(str(db))
    added: list[str] = []
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                model TEXT,
                cwd TEXT,
                started_at REAL,
                ended_at REAL,
                end_reason TEXT,
                parent_session_id TEXT,
                message_count INTEGER
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "source" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN source TEXT")
            added.append("source")
        conn.commit()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        return {
            "path": str(db),
            "source_column": "source" in cols,
            "added": added,
        }
    finally:
        conn.close()
