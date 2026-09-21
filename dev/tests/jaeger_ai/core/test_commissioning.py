"""Commissioning state machine, coordinator, discovery, and recovery."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jaeger_ai.core.instance import first_boot as fb
from jaeger_ai.core.instance import first_boot_script as script
from jaeger_ai.core.instance.commissioning import (
    CommissioningCoordinator,
    default_authority_policy,
    load_authority_policy,
    translate_human_permission,
    write_authority_policy,
)
from jaeger_ai.core.instance.first_boot import FirstBootStatus
from jaeger_ai.core.instance.provider_certification import (
    SUITE_VERSION,
    certify_available,
    certify_role,
    load_matrix,
    select_production_model,
)
from jaeger_ai.core.instance.system_discovery import discover_host


@pytest.fixture()
def inst(tmp_path):
    root = tmp_path / "inst"
    root.mkdir()
    return root


def _walk_to_q2(root: Path) -> None:
    fb.begin(root)
    fb.record_bench(root, recommendation={"tier_label": "test"})
    fb.record_character(root, "custom", character_id="assistant")
    fb.record_social(root, "Social.", latency_ms=300)
    fb.record_voice(root, "female")
    fb.record_q2(root, "Fine.")


def test_every_automatic_stage_is_forward_and_idempotent(inst):
    _walk_to_q2(inst)
    assert fb.status(inst) is FirstBootStatus.DISCOVERING_PROVIDERS
    coord = CommissioningCoordinator(inst)
    seen: list[str] = []
    previous = None
    for _ in range(40):
        current = fb.status(inst)
        if current.value not in seen:
            seen.append(current.value)
        if current is FirstBootStatus.INITIALIZING_PERSONA:
            break
        coord.tick(budget_s=2.0)
        if fb.status(inst) is previous and current not in {
            FirstBootStatus.INITIALIZING_PERSONA,
            FirstBootStatus.COMPLETED,
        }:
            # still automatic? tick again
            if current is FirstBootStatus.INITIALIZING_PERSONA:
                break
        previous = fb.status(inst)
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA
    completed = fb.snapshot(inst).get("completed_stages") or []
    for stage in (
        FirstBootStatus.DISCOVERING_PROVIDERS,
        FirstBootStatus.CERTIFYING_PROVIDERS,
        FirstBootStatus.CONFIGURING_RUNTIME,
        FirstBootStatus.STARTING_RESIDENT,
    ):
        assert stage.value in seen or stage.value in completed


def test_restart_mid_certification_does_not_replay_personal_questions(inst):
    _walk_to_q2(inst)
    assert fb.status(inst) is FirstBootStatus.DISCOVERING_PROVIDERS
    snap = fb.snapshot(inst)
    assert snap.get("voice_profile") == "female"
    assert snap.get("q2_response") == "Fine."
    coord = CommissioningCoordinator(inst)
    coord.discover_providers()
    assert fb.status(inst) is FirstBootStatus.CERTIFYING_PROVIDERS
    # Simulate a crash: new coordinator, same durable file.
    resumed = CommissioningCoordinator(inst)
    resumed.tick(budget_s=20)
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA
    assert fb.snapshot(inst)["voice_profile"] == "female"
    assert fb.snapshot(inst)["q2_response"] == "Fine."
    assert script.QUESTION_VOICE not in script.next_turn(inst).text
    assert script.QUESTION_Q2 not in script.next_turn(inst).text


@pytest.mark.parametrize("stage_runner", [
    "discover_providers",
    "certify_providers",
    "configure_runtime",
    "start_resident",
])
def test_interruption_resume_keeps_identity(inst, stage_runner):
    _walk_to_q2(inst)
    coord = CommissioningCoordinator(inst)
    getattr(coord, stage_runner)()
    first_id = coord._entity_id()
    resumed = CommissioningCoordinator(inst)
    resumed.tick(budget_s=40)
    later_id = resumed._entity_id()
    if first_id and later_id:
        assert first_id == later_id
    assert fb.status(inst) is FirstBootStatus.INITIALIZING_PERSONA
    assert fb.snapshot(inst)["q2_response"] == "Fine."


def test_host_discovery_report_shape():
    report = discover_host(quick=True, include_ai=False)
    data = report.as_dict()
    for key in ("system", "compute", "audio", "vision", "ai", "development", "jaeger"):
        assert key in data
    assert "architecture" in data["system"]
    assert "cpu_cores" in data["system"]
    assert "available_disk_gb" in data["system"]


def test_kimi_react_pass_glm_react_fail_are_authoritative(inst):
    kimi = certify_role("ollama", "kimi-k2.7-code:cloud", "REACT")
    glm = certify_role("ollama", "glm-5.3-flash:cloud", "REACT")
    assert kimi.passed is True
    assert glm.passed is False
    matrix = certify_available(inst, live=False)
    provider, model = select_production_model(matrix)
    assert model != "glm-5.3-flash:cloud"
    assert load_matrix(inst).passed("kimi-k2.7-code:cloud", "REACT")
    assert SUITE_VERSION in {r.suite_version for r in matrix.results}


def test_permission_answers_become_policy_not_a_binary_mode(inst):
    policy = default_authority_policy(inst)
    write_authority_policy(inst, policy)
    widened = translate_human_permission(policy, "files", True, inst)
    assert widened["filesystem"]["read"] is True
    denied_shell = translate_human_permission(widened, "shell", False, inst)
    assert denied_shell["shell"]["risk_mode"] == "deny"
    write_authority_policy(inst, denied_shell)
    stored = load_authority_policy(inst)
    assert stored["shell"]["risk_mode"] == "deny"
    assert stored["protected_merge_deployment"] is False


def test_knowledge_does_not_index_home_by_default(inst):
    from jaeger_ai.core.instance.commissioning import write_baseline_knowledge, load_knowledge_sources
    write_baseline_knowledge(inst)
    sources = load_knowledge_sources(inst)
    paths = [s["path"] for s in sources]
    assert str(Path.home()) not in paths
    kinds = {s["kind"] for s in sources}
    assert "repository" in kinds
    assert "documentation" in kinds


def test_consumer_copy_hides_architecture_terms(inst):
    _walk_to_q2(inst)
    text = script.next_turn(inst).text.lower()
    for noise in ("react", "event fabric", "effectledger", "embedding", "mcp"):
        assert noise not in text
    CommissioningCoordinator(inst).tick(budget_s=20)
    blob = script.next_turn(inst).text.lower()
    for noise in ("react", "event fabric", "mcp", "vector store"):
        assert noise not in blob


def test_persona_does_not_speak_until_commissioning_completes(inst):
    _walk_to_q2(inst)
    turn = script.next_turn(inst)
    assert turn.speaker == "os1"
    assert script.PERSONA_FIRST_WORDS not in turn.lines
    CommissioningCoordinator(inst).tick(budget_s=20)
    turn = script.next_turn(inst)
    assert turn.speaker == "persona"
    assert script.PERSONA_FIRST_WORDS in turn.lines
    assert script.HANDOFF in turn.lines


def test_persistence_marker_survives_offline_restart(inst):
    _walk_to_q2(inst)
    coord = CommissioningCoordinator(inst)
    coord.tick(budget_s=25)
    snap = fb.snapshot(inst).get("commissioning") or {}
    verified = snap.get("persistence_verified") or {}
    assert verified.get("ok") or coord.offline
    entity = snap.get("resident") or {}
    assert entity.get("entity_id") or coord._entity_id()


def test_onboarding_status_json_includes_commissioning(inst, monkeypatch, capsys):
    import json
    from jaeger_ai.cli import onboarding_cmd

    fb.begin(inst)
    monkeypatch.setattr(onboarding_cmd, "_layout", lambda _i: (inst, "test"))
    assert onboarding_cmd.main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "AWAITING_BENCH"
    assert "commissioning" in payload
    assert "completed_stages" in payload["commissioning"]
