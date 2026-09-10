from __future__ import annotations

import json
from pathlib import Path

from jaeger_agent.memory import memory

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.sessions import SessionStore
from jaeger_ai.features.ares_migration import AresMigrationService


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_migration_is_feature_scoped_idempotent_and_source_read_only(tmp_path) -> None:
    source = tmp_path / "ares"
    session = {
        "session_id": "ares-one",
        "title": "ARES session",
        "model": "test-model",
        "context_messages": [
            {"role": "user", "content": "question", "timestamp": 10},
            {"role": "assistant", "content": "answer", "timestamp": 11},
        ],
    }
    _write(source / "webui" / "sessions" / "ares-one.json", session)
    _write(source / "cron" / "jobs.json", {"jobs": [{
        "id": "job-one",
        "name": "daily-audit",
        "prompt": "audit",
        "schedule": "0 9 * * *",
    }]})
    _write(source / "webui" / "worker-rankings.json", {"events": [{
        "id": "rank-one",
        "worker_id": "codex_local",
        "task_kind": "code",
        "metrics": {"task_success": 80},
        "effectiveness": 75,
    }]})
    (source / "plans").mkdir()
    (source / "plans" / "plan.md").write_text("# Important plan", encoding="utf-8")

    layout = InstanceLayout(tmp_path / "jaeger")
    layout.ensure_dirs()
    memory.bind(layout)
    sessions = SessionStore(layout.memory_dir / "sessions.db")
    service = AresMigrationService(source, layout, sessions)
    source_before = (source / "plans" / "plan.md").read_bytes()

    first = service.migrate()
    second = service.migrate()

    assert first["ok"] and first["sessions"]["imported"] == 1
    assert first["schedules"]["imported"] == 1
    assert first["worker_health"]["imported"] == 1
    assert second["idempotent"] is True
    assert sessions.search("answer")[0]["origin"] == "ares"
    assert (source / "plans" / "plan.md").read_bytes() == source_before
    assert (layout.memory_dir / "ares_migration" / "documents" / "plans" / "plan.md").exists()
    sessions.close()


def test_retirement_rehearsal_requires_completed_migration_and_verified_backup(tmp_path) -> None:
    source = tmp_path / "ares"
    source.mkdir()
    layout = InstanceLayout(tmp_path / "jaeger")
    layout.ensure_dirs()
    memory.bind(layout)
    sessions = SessionStore(layout.memory_dir / "sessions.db")
    service = AresMigrationService(source, layout, sessions)
    assert not service.rehearse_retirement()["ready"]
    service.migrate()
    backup = tmp_path / "ares.zip"
    service.create_backup(backup)
    assert service.rehearse_retirement(backup)["ready"]
    sessions.close()
