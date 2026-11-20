"""Tests for state audit, secret-safe archive/restore, clean personal profile, and 10-step onboarding (§2 & §8)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance.onboarding_setup import complete_setup, onboarding_blueprint
from jaeger_ai.core.instance.profile_lifecycle import (
    archive_state_root,
    audit_state_root,
    create_clean_personal_profile,
    restore_archive,
    verify_archive,
)
from jaeger_ai.core.world.model import EpistemicProvenance
from jaeger_ai.core.world.store import SqliteWorldStore
from jaeger_ai.features.human_needs.store import HumanNeedsStore


def test_audit_archive_verify_and_restore_excludes_secrets(tmp_path: Path):
    src = tmp_path / "live_state"
    (src / "instances" / "jaeger").mkdir(parents=True)
    (src / "instances" / "mac-acceptance-20261019").mkdir(parents=True)
    (src / "worktrees" / "jaeger-task1").mkdir(parents=True)
    (src / "secrets").mkdir(parents=True)
    (src / "caller_tokens").mkdir(parents=True)

    # Plant synthetic secrets (must NEVER be copied into archive)
    (src / "secrets.env").write_text("API_KEY=DO_NOT_ARCHIVE\n", encoding="utf-8")
    (src / "secrets" / "vault.key").write_text("PRIVATE_KEY_MATERIAL", encoding="utf-8")
    (src / "caller_tokens" / "webui.token").write_text("TOKEN_SECRET", encoding="utf-8")

    # Plant real SQLite stores + config
    store = GatewaySessionStore(src / "gateway_sessions.sqlite3")
    store.ensure_session("s-dev-1", title="Dev session")
    world = SqliteWorldStore(src / "knowledge.sqlite3")
    world.record_claim("Robot", "status", "calibrated", EpistemicProvenance.VERIFIED)
    (src / "entity_identity.json").write_text(json.dumps({"entity_id": "ent-1", "display_name": "Jaeger"}), encoding="utf-8")
    (src / "instances" / "jaeger" / "config.yaml.bak-old").write_text("old: true\n", encoding="utf-8")

    # 1. Read-only audit classifies accurately
    audit = audit_state_root(src)
    assert audit["exists"] is True
    assert "secrets.env" in audit["categories"]["secrets_excluded_in_place"]
    assert "instances/mac-acceptance-20261019" in audit["categories"]["development_and_testing"]
    assert "worktrees" in audit["categories"]["development_and_testing"]
    assert all(db["integrity_ok"] for db in audit["sqlite_summary"])

    # 2. Archive + verify (SHA-256 + SQLite integrity + zero secret leaks)
    archive_dir = tmp_path / "archive_v1"
    manifest = archive_state_root(src, archive_dir)
    assert manifest["file_count"] >= 3
    assert "secrets.env" in manifest["excluded_secrets"]
    assert (archive_dir / "RESTORE.md").is_file()

    ver = verify_archive(archive_dir)
    assert ver["ok"] is True
    assert ver["secret_leaks"] == []
    assert ver["sqlite_failures"] == []
    assert not (archive_dir / "payload" / "secrets.env").exists()
    assert not (archive_dir / "payload" / "secrets").exists()

    # 3. Restore preserves live secrets in target and restores SQLite data intact
    restored = tmp_path / "restored_state"
    restored.mkdir()
    (restored / "secrets.env").write_text("LIVE_SECRET=PRESERVED\n", encoding="utf-8")
    res = restore_archive(archive_dir, restored, allow_existing=True)
    assert res["ok"] is True
    assert (restored / "secrets.env").read_text(encoding="utf-8") == "LIVE_SECRET=PRESERVED\n"
    reopened_world = SqliteWorldStore(restored / "knowledge.sqlite3")
    assert reopened_world.query_claims("Robot")[0].value == "calibrated"


def test_clean_personal_profile_and_ten_step_onboarding(tmp_path: Path, monkeypatch):
    clean_root = tmp_path / "personal_clean"
    monkeypatch.setenv("JAEGER_STATE_DIR", str(clean_root))

    created = create_clean_personal_profile(
        clean_root,
        autonomy="Full Auto",
        quiet_start_hour=22,
        quiet_end_hour=7,
        heartbeat_interval_minutes=30,
    )
    assert created["ok"] is True
    assert created["companion_name"] == "Truth"
    assert created["install_mode"] == "fresh_install"
    assert created["autonomy"] == "auto"
    assert all(v["ok"] for v in created["db_checks"].values())

    # Verify zero dev/test sessions, zero synthetic claims, zero fake goals
    conn = sqlite3.connect(clean_root / "gateway_sessions.sqlite3")
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM durable_tasks").fetchone()[0] == 0
    conn.close()
    assert SqliteWorldStore(clean_root / "knowledge.sqlite3").search_claims("")["claims"] == []
    assert HumanNeedsStore(clean_root / "human_needs.sqlite3").list_goals() == []

    # Verify 10-step onboarding blueprint & complete_setup persistence
    from jaeger_ai.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=Path(created["instance_dir"]))
    bp = onboarding_blueprint(layout)
    assert bp["install_mode"] == "fresh_install"
    assert len(bp["steps"]) == 10

    complete_setup(
        layout,
        {
            "character_id": "truth",
            "display_name": "Truth",
            "awake_provider": "ollama",
            "awake_model": "mistral-large-4:cloud",
            "autonomy": "auto",
            "quiet_start_hour": 23,
            "quiet_end_hour": 6,
            "heartbeat_interval_minutes": 45,
            "disabled_dimensions": ["self_transcendence"],
            "initial_goals": [{"title": "Daily focus routine", "dimension": "competence_esteem", "priority": 1}],
            "audio_input": "Insta360 Link 2",
            "camera_device": "Insta360 Link 2",
        },
    )
    hn = HumanNeedsStore(clean_root / "human_needs.sqlite3")
    prefs = hn.get_preferences()
    assert prefs["quiet_start_hour"] == 23
    assert prefs["heartbeat_interval_minutes"] == 45
    assert prefs["disabled_dimensions"] == ["self_transcendence"]
    assert len(hn.list_goals()) == 1
