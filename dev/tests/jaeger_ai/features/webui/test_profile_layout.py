"""Vendor WebUI home: state.db source column; no legacy Hermes home wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jaeger_ai.features.webui.service import profile_layout
from jaeger_ai.features.webui.service.profile_layout import ensure_agent_state_schema


def test_ensure_agent_state_schema_adds_missing_source_column(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    db = agent / "state.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)")
    conn.commit()
    conn.close()

    result = ensure_agent_state_schema(agent)

    assert result["source_column"] is True
    assert "source" in result["added"]
    cols = {
        row[1]
        for row in sqlite3.connect(str(db)).execute("PRAGMA table_info(sessions)")
    }
    assert "source" in cols


def test_ensure_agent_state_schema_creates_db_when_missing(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    result = ensure_agent_state_schema(agent)
    assert result["source_column"] is True
    assert Path(result["path"]).is_file()


def test_profile_display_name_helper() -> None:
    from jaeger_ai.features.webui.service.profile_layout import profile_display_name

    assert profile_display_name("default") == "Hermes Agent"
    assert profile_display_name(None) == "Hermes Agent"
    assert profile_display_name("jaeger") == "Jaeger AI"
    assert profile_display_name("openclaw") == "OpenClaw"
    assert profile_display_name("roundtable") == "Roundtable"


def test_legacy_hermes_home_helpers_are_gone() -> None:
    for name in ("prepare_webui_home", "link_shared_profiles", "ensure_webui_profile_layout",
                 "ensure_webui_config_yaml", "ensure_webui_env_dotenv", "ensure_profile_state_schemas"):
        assert not hasattr(profile_layout, name), name
