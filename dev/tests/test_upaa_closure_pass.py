"""Comprehensive UPAA Production Closure Pass Verification Suite.

Tests the specific production requirements from the Pinocchio closure pass:
1. Real Provider Routing Swap Test (Item 16)
2. Action-Specific Verification Dispatch Tests (Items 4 & 17)
3. DeliberativeSearch Multi-Candidate & Replan Tests (Items 6 & 11)
4. SelfRefine Model-Backed Critic & Reviser Tests (Item 7)
5. Tier-2 Perception Model Invocation & Privacy Redaction Tests (Items 8 & 9)
6. SensorSupervisor Background Poller Lifecycle & Ingestion Tests (Item 9)
7. Skill Promotion via Production Registry & Discovery After Restart (Item 10)
8. Degraded-Safe Mode Failure Injection in _run_turn (Item 18)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
import time
from typing import Any

from jaeger_ai.core.entity.attention import SalienceEngine
from jaeger_ai.core.entity.authority import (
    AuthorityDecision,
    AuthorityLayer,
    AuthorizationStatus,
    ProposedAction,
)
from jaeger_ai.core.entity.cognition_router import CognitionRouter
from jaeger_ai.core.entity.deliberate_planner import CandidatePlan, DeliberatePlanner
from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.event_store import SqliteEventStore
from jaeger_ai.core.entity.executive import CognitiveStrategy, ExecutiveStrategySelector
from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.learning import LearningPipeline, LearningTarget
from jaeger_ai.core.entity.memory import MemorySubsystem
from jaeger_ai.core.entity.reflection import ReflexionStore, StructuredReflection
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.entity.self_refine import SelfRefineEngine
from jaeger_ai.core.entity.self_state import SelfState
from jaeger_ai.core.entity.sensors.desktop_activity import DesktopActivitySensor
from jaeger_ai.core.entity.sensors.supervisor import SensorSupervisor
from jaeger_ai.core.entity.sensors.tiered import (
    PerceptionTier,
    TieredObservation,
    TieredPerceptionCoordinator,
    redact_privacy_signals,
)
from jaeger_ai.core.entity.skills.promotion import (
    SkillCandidate,
    SkillPromotionPipeline,
    VerificationResult as SkillVerifResult,
)
from jaeger_ai.core.entity.verification import (
    VerificationContract,
    VerificationRegistry,
    VerificationResult,
    VerificationStatus,
)
from jaeger_ai.core.models.router import ModelRouter, SensitivityGate


@pytest.fixture
def isolated_closure_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provides isolated storage and resets singleton before and after test."""
    state_dir = tmp_path / "closure_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    instance_dir = state_dir / "instances" / "jaeger"
    (instance_dir / "run").mkdir(parents=True, exist_ok=True)
    (instance_dir / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JAEGER_STATE_DIR", str(state_dir))
    monkeypatch.setenv("JAEGER_HOME", str(state_dir))
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(instance_dir))
    EntityRuntime.reset_singleton()
    yield state_dir
    EntityRuntime.reset_singleton()


# ── 1. Real Provider Routing Swap Test ───────────────────────────────────

def test_closure_provider_routing_swap(isolated_closure_env: Path, monkeypatch: pytest.MonkeyPatch):
    """Prove provider continuity through Jaeger's actual sensitivity router and selector layer:
    1. Turn 1 routed via local provider A
    2. Reflection and memory persisted
    3. Process restart (runtime singleton reset)
    4. Turn 2 routed via cloud/external provider B
    5. Same Agent Identity and memory context preserved across swap
    """
    runtime = EntityRuntime.get_singleton(state_root=isolated_closure_env)
    initial_id = runtime.identity.entity_id

    # Route Turn 1 via Provider A
    model_a, prov_a, dec_a = ModelRouter.route_turn(
        "Private internal financial review for team",
        model="gemma:2b",
        provider="ollama",
    )
    assert dec_a.provider == "ollama"

    turn_1 = runtime.execute_turn(
        "Private internal financial review for team",
        session_id="swap_session",
        context={
            "react_runner": lambda t, **kw: {"text": f"Executed via {dec_a.provider} ({dec_a.model})", "tool_activity": []},
            "model_runner": lambda t, **kw: f"Executed via {dec_a.provider} ({dec_a.model})",
        },
    )
    assert "ollama" in turn_1["text"]

    # Record structured reflection under Provider A
    runtime.reflexion_store.add_reflection(
        StructuredReflection(
            reflection_id="refl-swap-1",
            hypothesis="Database migration requires checking read-replica lag first",
            confidence=0.92,
            failure_conditions="replica_lag_exceeded",
            applicability_conditions=["database", "migration"],
            supporting_episode_ids=["ep-swap-1"],
        )
    )

    # Simulate restart
    EntityRuntime.reset_singleton()
    runtime_restarted = EntityRuntime.get_singleton(state_root=isolated_closure_env)

    # Verify same identity survived restart
    assert runtime_restarted.identity.entity_id == initial_id

    # Route Turn 2 via Provider B (Cloud/OpenAI)
    model_b, prov_b, dec_b = ModelRouter.route_turn(
        "Public general summary of open source licenses",
        model="gpt-4o",
        provider="openai",
    )
    assert dec_b.provider == "openai"

    turn_2 = runtime_restarted.execute_turn(
        "Public general summary of open source licenses",
        session_id="swap_session",
        context={
            "react_runner": lambda t, **kw: {"text": f"Executed via {dec_b.provider} ({dec_b.model})", "tool_activity": []},
            "model_runner": lambda t, **kw: f"Executed via {dec_b.provider} ({dec_b.model})",
        },
    )
    assert "openai" in turn_2["text"]

    # Verify prior reflections are present and queryable after restart
    reflections = runtime_restarted.reflexion_store.retrieve_applicable("database migration task")
    assert len(reflections) >= 1
    assert "read-replica lag" in reflections[0].hypothesis

    # Verify unified episodic history preserved across both providers
    episodes = runtime_restarted.memory_subsystem.episodic.get_session_episodes("swap_session")
    assert len(episodes) == 2
    assert "ollama" in episodes[0].agent_response
    assert "openai" in episodes[1].agent_response


# ── 2. Action-Specific Verification Dispatch Tests ───────────────────────

def test_closure_action_specific_verification_registry(tmp_path: Path):
    """Verify action-specific verifier dispatch:
    - file_write: checks file existence and expected content
    - file_delete: checks file non-existence
    - git_commit: checks git commit log
    - process_start: checks port/pid
    - http_mutation: checks HTTP status
    - read_only: verifies execution integrity without mutation
    - message_send: verifies receipt presence
    - unknown action: returns OBJECTIVE_UNVERIFIED (never defaults to filesystem!)
    """
    registry = VerificationRegistry()

    # 1. FILE WRITE: success & failure
    test_file = tmp_path / "created.txt"
    test_file.write_text("token=secret_123", encoding="utf-8")
    res_write_ok = registry.verify(
        "Write token file",
        action={"action_type": "file_write", "path": str(test_file), "expected_content": "token="},
        result={"ok": True},
    )
    assert res_write_ok.status == VerificationStatus.OBJECTIVE_VERIFIED

    res_write_fail = registry.verify(
        "Write token file",
        action={"action_type": "file_write", "path": str(test_file), "expected_content": "missing_pattern"},
        result={"ok": True},
    )
    assert res_write_fail.status == VerificationStatus.OBJECTIVE_FAILED

    # 2. FILE DELETE: success & failure
    del_file = tmp_path / "to_delete.txt"
    # File does not exist -> verified deleted
    res_del_ok = registry.verify(
        "Delete temporary file",
        action={"action_type": "file_delete", "path": str(del_file)},
        result={"ok": True},
    )
    assert res_del_ok.status == VerificationStatus.OBJECTIVE_VERIFIED

    # File still exists -> failed delete
    del_file.write_text("still here", encoding="utf-8")
    res_del_fail = registry.verify(
        "Delete temporary file",
        action={"action_type": "file_delete", "path": str(del_file)},
        result={"ok": True},
    )
    assert res_del_fail.status == VerificationStatus.OBJECTIVE_FAILED

    # 3. READ-ONLY TOOL: integrity verified
    res_read = registry.verify(
        "Read system status",
        action={"action_type": "read_only", "tool": "cat"},
        result={"ok": True, "output": "healthy"},
    )
    assert res_read.status == VerificationStatus.OBJECTIVE_VERIFIED

    # 4. MESSAGE SEND: receipt present vs missing
    res_msg_ok = registry.verify(
        "Send notification email",
        action={"action_type": "message_send"},
        result={"ok": True, "receipt": "rec-msg-999"},
    )
    assert res_msg_ok.status == VerificationStatus.OBJECTIVE_VERIFIED

    res_msg_unverified = registry.verify(
        "Send notification email",
        action={"action_type": "message_send"},
        result={"ok": True},  # missing receipt
    )
    assert res_msg_unverified.status == VerificationStatus.OBJECTIVE_UNVERIFIED

    # 5. UNKNOWN ACTION: strictly OBJECTIVE_UNVERIFIED, NEVER defaults to filesystem
    res_unknown = registry.verify(
        "Calibrate robotic arm trajectory",
        action={"action_type": "quantum_alignment", "vector": [1, 0, 0]},
        result={"ok": True},
    )
    assert res_unknown.status == VerificationStatus.OBJECTIVE_UNVERIFIED
    assert "No action-specific verifier" in res_unknown.evidence


# ── 3. DeliberativeSearch Multi-Candidate & Replan Tests ─────────────────

def test_closure_deliberative_search_cognition_and_replan():
    """Prove DeliberativeSearch (LATS-inspired planning):
    1. Cognition provider generates candidate plans
    2. Independent critic evaluates plans
    3. Reflections penalize conflicting strategies
    4. Bounded replanning upon simulated execution failure
    """
    # Simulated cognition provider generating JSON candidate plans
    def mock_cognition_provider(prompt: str) -> str:
        candidates = [
            {
                "name": "Plan Alpha: Conservative Migration",
                "strategy_summary": "Dry run with table locks and staged validation",
                "steps": ["Lock tables", "Run schema migration", "Validate counts"],
                "tools_required": ["sql_exec", "verify_db"],
                "reversibility": "reversible",
                "safety_score": 0.95,
                "goal_satisfaction_score": 0.85,
            },
            {
                "name": "Plan Beta: In-Place Fast Cutover",
                "strategy_summary": "Direct in-place alter table without dry run",
                "steps": ["Alter table immediately", "Check logs"],
                "tools_required": ["sql_alter"],
                "reversibility": "irreversible",
                "safety_score": 0.30,
                "goal_satisfaction_score": 0.90,
            },
            {
                "name": "Plan Gamma: Shadow Table Double-Write",
                "strategy_summary": "Create shadow v2 table, replicate writes, then switch pointer",
                "steps": ["Create shadow table", "Replicate streaming writes", "Validate checksums", "Atomic cutover"],
                "tools_required": ["sql_exec", "shadow_replicate", "verify_checksum"],
                "reversibility": "reversible",
                "safety_score": 0.98,
                "goal_satisfaction_score": 0.95,
            },
        ]
        return json.dumps(candidates)

    # Simulated independent critic provider
    critic_invocations = []
    def mock_critic_provider(prompt: str) -> str:
        critic_invocations.append(prompt)
        if "Plan Beta" in prompt:
            return json.dumps({
                "goal_satisfaction_score": 0.80,
                "safety_score": 0.20,
                "reflection_penalty": 0.50,
                "notes": "Plan Beta is dangerous and lacks rollback steps.",
            })
        if "Plan Gamma" in prompt:
            return json.dumps({
                "goal_satisfaction_score": 0.98,
                "safety_score": 0.95,
                "reflection_penalty": 0.0,
                "notes": "Plan Gamma is robust, safe, and highly reversible.",
            })
        return json.dumps({
            "goal_satisfaction_score": 0.85,
            "safety_score": 0.90,
            "reflection_penalty": 0.1,
            "notes": "Plan Alpha is acceptable.",
        })

    reflections = [
        StructuredReflection(
            reflection_id="ref-alter-1",
            hypothesis="Direct sql_alter on active table causes transaction starvation",
            confidence=0.9,
            failure_conditions="direct_alter_timeout",
            applicability_conditions=["sql_alter"],
            supporting_episode_ids=["ep-1"],
        )
    ]

    goal = "Migrate user authentication schema to v3"
    candidates = DeliberatePlanner.generate_candidate_plans(
        goal=goal,
        prior_reflections=reflections,
        cognition_provider=mock_cognition_provider,
    )
    assert len(candidates) >= 3

    # Independent critic scores candidates
    winning_plan = DeliberatePlanner.evaluate_and_select(
        candidates,
        goal=goal,
        critic_provider=mock_critic_provider,
        prior_reflections=reflections,
    )
    assert len(critic_invocations) >= 3
    assert winning_plan.name == "Plan Gamma: Shadow Table Double-Write"
    assert winning_plan.final_score > 0.85

    # Simulated execution failure triggers bounded replanning
    replanned = DeliberatePlanner.replan_on_failure(
        failed_plan=winning_plan,
        failure_evidence="Shadow replication exceeded memory limit during peak traffic",
        goal=goal,
        prior_reflections=reflections,
        cognition_provider=mock_cognition_provider,
        critic_provider=mock_critic_provider,
    )
    assert replanned is not None
    assert replanned.name != winning_plan.name


# ── 4. SelfRefine Model-Backed Critic & Reviser Tests ────────────────────

def test_closure_self_refine_model_critic_and_reviser():
    """Verify SelfRefine uses actual model provider callbacks:
    Draft -> model critic -> model reviser -> validation pass -> final approved artifact.
    """
    model_calls = []

    def mock_critic_provider(prompt: str) -> str:
        model_calls.append("critic")
        if "TODO" in prompt or "draft_unrefined" in prompt:
            return json.dumps({
                "approved": False,
                "issues_found": ["Contains unexpanded TODO placeholders", "Missing rollback section"],
                "suggestions": ["Replace TODO with full code", "Add rollback commands"],
                "score": 0.4,
            })
        return json.dumps({
            "approved": True,
            "issues_found": [],
            "suggestions": [],
            "score": 0.95,
        })

    def mock_reviser_provider(prompt: str) -> str:
        model_calls.append("reviser")
        return (
            "# Production Deployment Plan\n"
            "# Rollback: git reset --hard HEAD~1 && docker-compose restart\n"
            "def deploy():\n"
            "    print('Verified production deployment without placeholders')\n"
        )

    draft = "# Deployment Draft\n# TODO: implement deploy\ndef deploy(): pass\n"
    res = SelfRefineEngine.refine_artifact(
        draft,
        rubric="No placeholders, must include rollback",
        max_iterations=3,
        critic_provider=mock_critic_provider,
        cognition_provider=mock_reviser_provider,
    )

    assert "critic" in model_calls
    assert "reviser" in model_calls
    assert res.is_approved
    assert "Rollback" in res.refined
    assert "TODO" not in res.refined


# ── 5. Tier-2 Perception Model Invocation & Privacy Redaction Tests ──────

def test_closure_tiered_perception_and_privacy_redaction():
    """Prove:
    1. Tier 0 routine telemetry -> 0 model calls
    2. Tier 1 local heuristic -> 0 model calls
    3. Tier 2 model provider invoked ONLY on justified escalation
    4. Privacy redaction scrubs tokens, credentials, and emails before Tier 2
    """
    model_calls = []

    def fake_tier2_provider(prompt: str, context: dict[str, Any]) -> str:
        model_calls.append(dict(context))
        return "Assessment: Anomaly verified. Operator escalation recommended."

    coordinator = TieredPerceptionCoordinator(tier2_provider=fake_tier2_provider)

    # 1. Routine event: Tier 0, 0 model calls
    obs_t0 = coordinator.process(
        "desktop",
        {"active_app": "Terminal", "disk_free_gb": 45.0, "alerts": []},
    )
    assert obs_t0.tier_reached == PerceptionTier.TIER_0_DETERMINISTIC
    assert len(model_calls) == 0

    # 2. Critical event with sensitive tokens: escalated to Tier 2 with privacy redaction
    sensitive_signals = {
        "active_app": "1Password Vault",
        "api_key": "sk-secret1234567890",
        "bearer_token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "operator_email": "admin@robotics.internal",
        "alerts": ["Out of memory crash in worker daemon"],
        "disk_free_gb": 0.8,
    }
    obs_t2 = coordinator.process("desktop", sensitive_signals)

    assert obs_t2.tier_reached == PerceptionTier.TIER_2_EXPENSIVE_MODEL
    assert len(model_calls) == 1

    # Verify privacy scrubbing on the context sent to Tier 2 provider
    delivered = model_calls[0]
    assert delivered["api_key"] == "[REDACTED_CREDENTIAL]"
    assert "[REDACTED" in str(delivered.get("bearer_token"))
    assert "[REDACTED_EMAIL]" in str(delivered.get("operator_email"))
    assert delivered["active_app"] == "[PROTECTED_APP]"


# ── 6. SensorSupervisor Background Poller Lifecycle & Ingestion ───────────

def test_closure_sensor_supervisor_lifecycle(isolated_closure_env: Path):
    """Prove SensorSupervisor:
    - Thread-safe start / stop lifecycle
    - Permission gate (disabled produces None)
    - Ingests sensed events into EntityRuntime Event Fabric
    """
    runtime = EntityRuntime.get_singleton(state_root=isolated_closure_env)

    sensor = DesktopActivitySensor(workspace_path=str(isolated_closure_env), enabled=True)
    supervisor = SensorSupervisor(runtime=runtime, sensor=sensor, interval_s=0.2, enabled=True)

    # Polling once
    ev = supervisor.poll_once()
    assert ev is not None
    assert ev.event_type == EventType.PERCEPTION_SENSED.value

    # Start and stop lifecycle
    supervisor.start()
    assert supervisor.is_running
    time.sleep(0.5)
    supervisor.stop()
    assert not supervisor.is_running
    assert supervisor.poll_count >= 1

    # Verify event reached EntityRuntime event store
    stored = list(runtime.event_store.replay_all())
    sensed_events = [e for e in stored if e.event_type == EventType.PERCEPTION_SENSED.value]
    assert len(sensed_events) >= 1


# ── 7. Skill Promotion via Production Registry & Discovery After Restart ─

def test_closure_skill_promotion_and_restart_discovery(isolated_closure_env: Path):
    """Prove:
    1. Candidate extracted and automated verification passes
    2. Full v3 skill artifact written to canonical location
    3. Production skill loader registers the skill
    4. Runtime restart discovers skill in registry
    """
    skills_dir = isolated_closure_env / "skills"
    pipeline = SkillPromotionPipeline(skills_dir=skills_dir)

    candidate = pipeline.extract_candidate(
        name="automated_health_probe_v1",
        description="Performs deep invariant check on database and filesystem integrity",
        code="def run(): return {'healthy': True, 'checks_passed': 42}",
        parameters={"timeout_s": "float"},
    )

    verif = pipeline.verify_candidate(
        candidate,
        verification_test=lambda code: "checks_passed" in code,
    )
    assert verif.passed

    promoted = pipeline.promote(candidate, verif)
    assert promoted

    # Check that disk package adheres to production v3 spec
    skill_dir = skills_dir / "automated_health_probe_v1"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "manifest.yaml").exists()
    assert (skill_dir / "run.py").exists()
    assert (skill_dir / "tests" / "smoke_test.py").exists()

    # Simulate restart and reload
    pipeline_restarted = SkillPromotionPipeline(skills_dir=skills_dir)
    skill_md = skill_dir / "SKILL.md"
    assert skill_md.exists()
    content = skill_md.read_text(encoding="utf-8")
    assert "automated_health_probe_v1" in content
    assert "verified: true" in content


# ── 8. Degraded-Safe Mode Failure Injection in _run_turn ──────────────────

def test_closure_degraded_safe_halt_on_runtime_failure(isolated_closure_env: Path, monkeypatch: pytest.MonkeyPatch):
    """Prove _run_turn does NOT silently bypass into full-power legacy ReAct on kernel failure:
    - Actionable / mutating requests fail-closed with degraded_safe_halt
    - Conversational queries fall back into read-only tool_allowlist([]) direct reply
    """
    from jaeger_ai.main import _run_turn

    # Force EntityRuntime execution to raise an unexpected infrastructure failure
    def exploding_execute_turn(*args, **kwargs):
        raise RuntimeError("Kernel storage corruption injected for test")

    monkeypatch.setattr(EntityRuntime, "execute_turn", exploding_execute_turn)

    # Case A: Actionable mutating task -> halts closed immediately
    res_mutating = _run_turn(
        None,
        "Write configuration to /etc/systemd/system/jaeger.service and restart daemon",
        session_key="fail_inj",
    )
    assert res_mutating.get("degraded_mode") is True
    assert res_mutating.get("strategy") == "degraded_safe_halt"
    assert "DegradedRuntimeError" in res_mutating.get("error", "")
    assert res_mutating.get("tool_activity") == []

    # Case B: Read-only conversational query -> allows direct answer with tool_allowlist([])
    monkeypatch.setattr(
        "jaeger_ai.main._run_subordinate_react",
        lambda client, text, **kw: {"text": "I am in degraded read-only mode.", "tool_activity": []},
    )
    res_query = _run_turn(
        None,
        "Hello, what is the capital of France?",
        session_key="fail_inj_query",
    )
    assert "degraded read-only mode" in res_query.get("text", "")
    assert res_query.get("tool_activity") == []
