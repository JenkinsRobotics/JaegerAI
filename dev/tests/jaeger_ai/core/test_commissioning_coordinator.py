"""Integration tests for CommissioningCoordinator on an isolated instance."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.instance import first_boot as fb
from jaeger_ai.core.instance.commissioning import CommissioningCoordinator
from jaeger_ai.core.instance.first_boot import FirstBootStatus
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, Identity, ModelConfig, dump_yaml


@pytest.fixture()
def layout(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_COMMISSIONING_OFFLINE", "1")
    monkeypatch.delenv("JAEGER_COMMISSIONING_LIVE", raising=False)
    root = tmp_path / "instances" / "fresh"
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(name="Assistant", role="assistant", personality="helpful"))
    dump_yaml(layout.config_path, Config(instance_name="fresh", model=ModelConfig(model_path="/dev/null")))
    layout.manifest_path.write_text("{}", encoding="utf-8")
    EntityRuntime.reset_singleton()
    yield layout
    EntityRuntime.reset_singleton()


def _calibrate(layout: InstanceLayout) -> None:
    fb.begin(layout)
    fb.record_bench(layout, recommendation={"tier_label": "test"})
    fb.record_character(layout, "custom", character_id="assistant")
    fb.record_social(layout, "Social.", latency_ms=250)
    fb.record_voice(layout, "male")
    fb.record_q2(layout, "Close.")


def test_full_offline_coordinator_reaches_persona(layout):
    _calibrate(layout)
    coord = CommissioningCoordinator(layout)
    assert coord.offline is True
    status = coord.tick(budget_s=40)
    assert status is FirstBootStatus.INITIALIZING_PERSONA
    report = coord.snapshot()
    assert report["entity_id"]
    assert report["provider_certifications"]["assignments"]
    assert report["approved_knowledge_sources"]
    policy = layout.root / "authority_policy.yaml"
    assert policy.is_file()
    assert (layout.memory_dir / "commissioning_marker.txt").is_file()
    assert fb.persona_name(layout) or fb.snapshot(layout).get("calibration_source") == "character_preset"


def test_complete_runs_commissioning_then_finishes(layout):
    _calibrate(layout)
    assert fb.complete(layout) is FirstBootStatus.COMPLETED
    assert fb.is_complete(layout)


def test_validation_records_disk_evidence_not_imports(layout):
    from jaeger_ai.core.instance.commissioning_validation import run_validation

    _calibrate(layout)
    CommissioningCoordinator(layout).tick(budget_s=40)
    report = run_validation(layout, offline=True)
    action = next(c for c in report.checks if c.id == "safe_tool_execution")
    assert action.kind == "STRUCTURAL"
    assert action.status == "STRUCTURAL_OK"
    assert action.passed is True
    fabric = next(c for c in report.checks if c.id == "event_fabric")
    assert "count=" in fabric.evidence or fabric.passed


def test_repair_creates_missing_memory_dir(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.commissioning_repair import RepairAttempt, apply_repair
    from jaeger_ai.core.instance.commissioning_validation import CheckResult

    monkeypatch.setenv("JAEGER_COMMISSIONING_OFFLINE", "1")
    root = tmp_path / "broken"
    root.mkdir()
    attempt = apply_repair(root, RepairAttempt(
        check_id="memory_store", action="create_memory_dir", applied=False, safe=True,
    ))
    assert attempt.applied is True
    assert (root / "memory").is_dir()
    # unsafe actions stay human
    denied = apply_repair(root, RepairAttempt(
        check_id="gateway", action="invent_credentials", applied=False, safe=False, needs_human=True,
    ))
    assert denied.applied is False
    assert denied.needs_human is True
    _ = CheckResult


def test_capability_registry_tracks_authorization(layout):
    from jaeger_ai.core.instance.capability_discovery import discover_capabilities, load_registry
    from jaeger_ai.core.instance.commissioning import default_authority_policy, write_authority_policy

    write_authority_policy(layout, default_authority_policy(layout))
    registry = discover_capabilities(layout, host={"system": {"available_disk_gb": 40, "os": "Darwin"},
                                                   "audio": {}, "vision": {}, "ai": {}, "development": {"git": True},
                                                   "compute": {}},
                                     policy=default_authority_policy(layout))
    saved = load_registry(layout)
    assert saved.get("filesystem.read").authorized is True
    assert saved.get("filesystem.write").available is True
    assert registry.get("shell").authorized is True
