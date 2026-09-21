"""Operational OS spec gates: ownership, status, idempotency mapping, index, reflexion constraints."""

from __future__ import annotations

from pathlib import Path
import json

import pytest

from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.indexing import IndexCoordinator
from jaeger_ai.core.entity.ownership import EntityRuntimeMode, migrate_legacy_entity_state
from jaeger_ai.core.entity.reflection import ReflexionStore, StructuredReflection
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.runtime.maintenance import MaintenanceCoordinator, PROTECTED_PATH_MARKERS
from jaeger_ai.core.runtime.native_turns import _terminal_status


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JAEGER_INSTANCE_NAME", "jaeger")
    EntityRuntime.reset_singleton()
    yield tmp_path
    EntityRuntime.reset_singleton()


def test_instance_layout_entity_paths(tmp_path: Path):
    layout = InstanceLayout(root=tmp_path / "instances" / "jaeger")
    layout.ensure_dirs()
    assert layout.event_store_path == layout.memory_dir / "entity_events.sqlite3"
    assert layout.entity_identity_path.parent == layout.memory_dir
    assert layout.resident_lock_path.parent == layout.run_dir
    assert layout.skills_dir == layout.root / "skills"


def test_migrate_legacy_entity_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    op = tmp_path / "op"
    inst = tmp_path / "instances" / "jaeger"
    op.mkdir()
    (op / "entity_identity.json").write_text(
        json.dumps({
            "entity_id": "jaeger-entity-migrated",
            "display_name": "Jaeger",
            "created_at": 1.0,
            "instance_name": "jaeger",
        }),
        encoding="utf-8",
    )
    (op / "entity_events.sqlite3").write_bytes(b"sqlite-placeholder")
    monkeypatch.setenv("JAEGER_STATE_DIR", str(op))
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(inst))
    layout = InstanceLayout(root=inst)
    migrate_legacy_entity_state(layout)
    assert layout.entity_identity_path.is_file()
    assert "jaeger-entity-migrated" in layout.entity_identity_path.read_text()
    assert layout.event_store_path.is_file()


def test_runtime_mode_test_does_not_schedule(isolated: Path):
    EntityRuntime.reset_singleton()
    rt = EntityRuntime.get_singleton(state_root=isolated, mode=EntityRuntimeMode.TEST)
    assert rt.mode == EntityRuntimeMode.TEST
    assert rt.event_store.path.parent == isolated
    EntityRuntime.reset_singleton()
    client = EntityRuntime.get_singleton(state_root=isolated, mode=EntityRuntimeMode.ATTACHED_CLIENT)
    assert client.mode == EntityRuntimeMode.ATTACHED_CLIENT
    assert client.is_resident is False


def test_native_complete_task_is_completed():
    assert _terminal_status({"text": "Stored LYRE", "halt_reason": "complete_task", "halt_code": "agent_halted", "error": None}) == "completed"
    assert _terminal_status({"error": "boom", "halt_reason": "error"}) == "failed"
    assert _terminal_status({"cancelled": True}) == "cancelled"


def test_background_completed_payload(isolated: Path):
    EntityRuntime.reset_singleton()
    rt = EntityRuntime(state_root=isolated, mode=EntityRuntimeMode.TEST)
    ev = rt.record_background_completed(
        "task-1",
        {"summary": "wrote tonight.txt", "artifact_refs": ["tonight.txt"], "originating_event_id": "msg-1"},
        session_id="webui-1",
    )
    assert ev.event_type == EventType.BACKGROUND_COMPLETED.value
    assert ev.payload["task_id"] == "task-1"
    assert ev.payload["source_session"] == "webui-1"
    assert ev.payload["status"] == "completed"
    assert ev.payload["artifact_refs"] == ["tonight.txt"]


def test_reflexion_planning_constraint(isolated: Path):
    store = ReflexionStore(isolated)
    store.add_reflection(
        StructuredReflection(
            reflection_id="refl-sql",
            hypothesis="direct_sql_alter caused lock starvation",
            confidence=0.91,
            failure_conditions="read_file:not found",
            applicability_conditions=["read_file", "filesystem"],
            supporting_episode_ids=["msg-a"],
        )
    )
    block = store.to_planning_constraints("Use the read_file tool to open missing.txt")
    assert "AVOID / PENALIZE first-action `read_file`" in block
    assert "refl-sql" in block


def test_index_skips_unchanged(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello index", encoding="utf-8")
    coord = IndexCoordinator(tmp_path / "memory")
    first = coord.sweep(docs_dir=docs, max_files=10)
    assert first["updated"] >= 1
    second = coord.sweep(docs_dir=docs, max_files=10)
    assert second["updated"] == 0
    assert second["skipped"] >= 1
    hits = coord.retrieve("hello")
    assert hits
    assert hits[0]["provenance"] == "RETRIEVED_DOCUMENT"
    (docs / "nebula.txt").write_text("NEBULA-COMMISSIONING-INDEX\n", encoding="utf-8")
    coord.sweep(docs_dir=docs, max_files=10)
    asked = coord.retrieve("What does the commissioning index source say? Quote the unique phrase.")
    assert any("NEBULA-COMMISSIONING-INDEX" in str(h.get("text") or "") for h in asked)


def test_extra_sources_are_indexed_before_docs(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(20):
        (docs / f"a{i}.md").write_text(
            f"commissioning index source document {i} without the unique phrase\n",
            encoding="utf-8",
        )
    extra = tmp_path / "index-src"
    extra.mkdir()
    (extra / "commissioning-index-source.txt").write_text("NEBULA-COMMISSIONING-INDEX\n", encoding="utf-8")
    coord = IndexCoordinator(tmp_path / "memory")
    result = coord.sweep(docs_dir=docs, extra=[extra], max_files=40)
    assert result["updated"] >= 1
    hits = coord.retrieve("What does the commissioning index source say?")
    assert hits
    assert "NEBULA-COMMISSIONING-INDEX" in str(hits[0].get("text") or "")
    assert "index-src" in str(hits[0].get("source_id") or "")


def test_maintenance_skips_protected_paths(tmp_path: Path):
    coord = MaintenanceCoordinator(tmp_path)
    item = coord.select_item([{"id": "sec", "path": "jaeger_ai/core/entity/authority.py"}])
    assert item is None
    assert any("authority" in m for m in PROTECTED_PATH_MARKERS)
    picked = coord.select_item([{"id": "docs", "path": "docs/architecture/note.md"}])
    assert picked is not None
    result = coord.run_cycle(picked, dry_run=True)
    assert result.status in {"candidate", "BLOCKED"}


def test_runtime_status_schema(isolated: Path):
    EntityRuntime.reset_singleton()
    EntityRuntime.get_singleton(state_root=isolated, mode=EntityRuntimeMode.TEST)
    from jaeger_ai.core.entity.runtime_status import collect_runtime_status, HealthStatus
    doc = collect_runtime_status(include_network=False)
    for key in ("Agent", "Runtime", "Provider", "Services", "Background", "Storage", "Work"):
        assert key in doc
    assert "entity_id" in doc["Agent"]
    assert doc["Agent"]["status"] in {s.value for s in HealthStatus}
