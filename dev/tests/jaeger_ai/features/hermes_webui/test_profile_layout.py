"""Vendor WebUI home: shared profiles symlink and state.db source column."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jaeger_ai.features.hermes_webui.profile_layout import (
    ensure_agent_state_schema,
    ensure_webui_profile_layout,
    link_shared_profiles,
    prepare_vendor_webui_home,
)


def test_link_replaces_leftover_real_profiles_directory(tmp_path: Path) -> None:
    shared = tmp_path / "shared" / "profiles"
    shared.mkdir(parents=True)
    (shared / "jaeger").mkdir()
    agent = tmp_path / "agent"
    leftover = agent / "profiles"
    leftover.mkdir(parents=True)
    (leftover / "stale.txt").write_text("isolated", encoding="utf-8")

    result = link_shared_profiles(shared=shared, agent_home=agent)

    assert result["linked"] is True
    assert result["replaced"]
    target = agent / "profiles"
    assert target.is_symlink()
    assert target.resolve() == shared.resolve()
    assert Path(result["replaced"]).is_dir()
    assert (Path(result["replaced"]) / "stale.txt").read_text(encoding="utf-8") == "isolated"


def test_link_is_idempotent_when_already_correct(tmp_path: Path) -> None:
    shared = tmp_path / "shared" / "profiles"
    shared.mkdir(parents=True)
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "profiles").symlink_to(shared, target_is_directory=True)

    result = link_shared_profiles(shared=shared, agent_home=agent)

    assert result["linked"] is True
    assert result["replaced"] is None
    assert (agent / "profiles").is_symlink()


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


def test_prepare_vendor_webui_home_wires_layout_link_and_schema(tmp_path: Path) -> None:
    hermes = tmp_path / "hermes"
    (hermes / "profiles" / "jaeger").mkdir(parents=True)
    (hermes / "profiles" / "openclaw").mkdir()
    (hermes / "profiles" / "roundtable").mkdir()
    agent = tmp_path / "vendor-agent"
    leftover = agent / "profiles"
    leftover.mkdir(parents=True)

    result = prepare_vendor_webui_home(agent, hermes_home=hermes)

    assert result["state_db"]["source_column"] is True
    assert result["profiles"]["linked"] is True
    assert (agent / "profiles").is_symlink()
    names = result["layout"]["visible_named_profiles"]
    assert "jaeger" in names
    assert "openclaw" in names
    assert "roundtable" in names
    yaml = (hermes / "profiles" / "jaeger" / "profile.yaml").read_text(encoding="utf-8")
    assert "display_name: Jaeger" in yaml
    assert "display_name: Hermes Agent" in (agent / "profile.yaml").read_text(encoding="utf-8")


def test_ensure_webui_profile_layout_keeps_named_profiles_visible(tmp_path: Path) -> None:
    home = tmp_path / ".hermes"
    (home / "profiles" / "jaeger").mkdir(parents=True)
    (home / "profiles" / "openclaw").mkdir()
    result = ensure_webui_profile_layout(home)
    assert result["archived"] == []
    assert "jaeger" in result["visible_named_profiles"]
    assert "openclaw" in result["visible_named_profiles"]


def test_prepare_writes_vendor_default_and_named_display_names(tmp_path: Path) -> None:
    hermes = tmp_path / "hermes"
    (hermes / "profiles" / "jaeger").mkdir(parents=True)
    (hermes / "profiles" / "openclaw").mkdir()
    (hermes / "profiles" / "roundtable").mkdir()
    agent = tmp_path / "vendor-agent"

    result = prepare_vendor_webui_home(agent, hermes_home=hermes)

    assert result["display_names"]["default"] == "Hermes Agent"
    assert result["display_names"]["jaeger"] == "Jaeger"
    assert result["display_names"]["openclaw"] == "OpenClaw"
    assert result["display_names"]["roundtable"] == "Roundtable"
    agent_yaml = (agent / "profile.yaml").read_text(encoding="utf-8")
    assert "display_name: Hermes Agent" in agent_yaml
    assert "display_name: Hermes Agent" in (hermes / "profile.yaml").read_text(encoding="utf-8")
    assert "display_name: OpenClaw" in (hermes / "profiles" / "openclaw" / "profile.yaml").read_text(encoding="utf-8")
    assert "display_name: Roundtable" in (agent / "profiles" / "roundtable" / "profile.yaml").read_text(encoding="utf-8")


def test_profile_display_name_helper() -> None:
    from jaeger_ai.features.hermes_webui.profile_layout import profile_display_name

    assert profile_display_name("default") == "Hermes Agent"
    assert profile_display_name(None) == "Hermes Agent"
    assert profile_display_name("jaeger") == "Jaeger"
    assert profile_display_name("openclaw") == "OpenClaw"
    assert profile_display_name("roundtable") == "Roundtable"
