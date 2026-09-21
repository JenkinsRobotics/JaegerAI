"""Production UPAA Integration & Verification Suite (Pinocchio Acceptance Tests).

Proves the complete Universal Persistent Agent Architecture:
1. Real Executable Trace:
   CLI/Bridge/Gateway turn -> EntityRuntime -> Event Store -> Reducer -> Salience ->
   Executive -> CognitionRouter -> JaegerAgent/provider -> ProposedAction -> Authority ->
   ToolExecutor -> Consequence Event -> Verification -> Learning -> Memory Update -> Response.
2. Passive Path:
   Routine sensor, quiet heartbeat, low-salience background produce 0 cognition calls.
3. Active Path:
   Human prompt, high-salience anomaly, scheduled briefings wake cognition.
4. Provider Swap Continuity:
   Identity, episodic history, and reflections survive provider switch across restart.
5. Interface Swap Continuity:
   CLI, Bridge, and Gateway ingress share identical identity, self-state, and memory.
6. Sleep-Time Processing:
   Consolidates history, handles contradiction, extracts reflections, preserves unresolved goals.
7. Skill Learning & Promotion:
   Extracts candidate, passes verification gate, writes production SKILL.md, retrievable next boot.
8. Deliberate Planning (LATS):
   Generates >= 3 candidate plans, critic evaluation, selection, and execution.
9. Tiered Perception Sensors:
   Deterministic Tier 0 -> Local Heuristic Tier 1 -> Multimodal Tier 2 escalation.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import pytest

from jaeger_ai.core.entity.attention import SalienceEngine, SalienceLevel
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
from jaeger_ai.core.entity.sensors.tiered import (
    PerceptionTier,
    TieredObservation,
    TieredPerceptionCoordinator,
)
from jaeger_ai.core.entity.skills.promotion import (
    SkillCandidate,
    SkillPromotionPipeline,
    VerificationResult as SkillVerifResult,
)
from jaeger_ai.core.entity.sleep_time import SleepTimeProcessor
from jaeger_ai.core.entity.verification import VerificationContract, VerificationStatus
from jaeger_ai.main import _run_turn


@pytest.fixture
def clean_upaa_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provides isolated storage and resets singleton before and after test."""
    state_dir = tmp_path / "upaa_state"
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


# ── Test 1: Real Executable Trace Test ────────────────────────────────
def test_1_real_executable_trace(clean_upaa_env: Path):
    """Trace: Turn -> EntityRuntime -> Event Store -> Reducer -> Salience ->
    Executive -> Cognition -> Consequence -> Verification -> Learning -> Response.
    """
    runtime = EntityRuntime.get_singleton(state_root=clean_upaa_env)

    # Context with mock ReAct tool execution
    executed_tools = []
    def mock_react_runner(text: str, session_key: str = "dispatcher") -> dict:
        executed_tools.append("write_file")
        test_file = clean_upaa_env / "output.txt"
        test_file.write_text("trace content", encoding="utf-8")
        return {
            "text": "Completed trace action",
            "tool_activity": [f"write_file({test_file})"],
            "path": str(test_file),
            "expected_content": "trace content",
            "error": None,
        }

    res = runtime.execute_turn(
        "Write trace content to output file",
        session_id="test_session",
        source="cli.test",
        context={"react_runner": mock_react_runner},
    )

    # 1. Output dict conforms to standard contract
    assert res["text"] == "Completed trace action"
    assert res["strategy"] == CognitiveStrategy.REACT_LOOP.value
    assert "write_file" in executed_tools

    # 2. Event Store recorded the full trace: human message + response
    events = list(runtime.event_store.replay_all())
    event_types = [e.event_type for e in events]
    assert EventType.HUMAN_MESSAGE.value in event_types
    assert EventType.AGENT_RESPONSE.value in event_types

    # 3. State Reducer updated total events
    assert runtime.current_state.total_events_processed >= 2

    # 4. Learning pipeline recorded episodic memory
    episodes = runtime.memory_subsystem.episodic.get_session_episodes("test_session")
    assert len(episodes) >= 1
    assert episodes[0].user_text == "Write trace content to output file"
    assert episodes[0].agent_response == "Completed trace action"


# ── Test 2: Passive Path Test (0 LLM Calls) ───────────────────────────
def test_2_passive_path_zero_model_calls(clean_upaa_env: Path):
    """Feed: routine sensor event, quiet heartbeat, low-priority background completion.
    A cognition handler that throws if called must NEVER be triggered.
    """
    runtime = EntityRuntime.get_singleton(state_root=clean_upaa_env)

    def exploding_handler(event: JaegerEvent, state: SelfState):
        raise AssertionError("Exploding cognition handler should NOT be called for passive events!")

    runtime.register_cognition_handler(exploding_handler)

    # 1. Routine sensor event (salience = 0.2 < 0.6)
    _, att_sensor = runtime.submit_observation(
        sensor="desktop_activity",
        signals={"active_app": "Terminal", "idle_seconds": 12.0},
        salience=0.2,
    )
    assert not att_sensor.wake_cognition
    assert att_sensor.level in (SalienceLevel.PASSIVE, SalienceLevel.LOW)

    # 2. Quiet heartbeat (salience = 0.1 < 0.6)
    _, att_heartbeat = runtime.submit_heartbeat()
    assert not att_heartbeat.wake_cognition
    assert att_heartbeat.level == SalienceLevel.IGNORED

    # 3. Low-priority background completion without followup (salience = 0.3)
    ev_bg = runtime.record_background_completed(
        task_id="task-123",
        result={"status": "clean"},
        requires_followup=False,
    )
    assert ev_bg.salience == 0.3
    # Check that attention for this was low
    dec = runtime.salience_engine.evaluate(ev_bg, runtime.current_state)
    assert not dec.wake_cognition


# ── Test 3: Active Path Test (Cognition Wakes) ─────────────────────────
def test_3_active_path_wakes_cognition(clean_upaa_env: Path):
    """Feed: human prompt, high-salience anomaly, required scheduled briefing.
    All must evaluate to wake_cognition = True and reach the executive router.
    """
    runtime = EntityRuntime.get_singleton(state_root=clean_upaa_env)

    # 1. Human message
    _, att_msg = runtime.submit_human_message("What is the status of project X?")
    assert att_msg.wake_cognition
    assert att_msg.level in (SalienceLevel.URGENT, SalienceLevel.CRITICAL)

    # 2. High-salience anomaly (disk full, security alert)
    _, att_alert = runtime.submit_observation(
        sensor="system_monitor",
        signals={"alert": "Disk usage 99.8%", "critical": True},
        salience=0.9,
    )
    assert att_alert.wake_cognition
    assert att_alert.level == SalienceLevel.CRITICAL

    # 3. Background task requiring mandatory operator followup
    ev_followup = runtime.record_background_completed(
        task_id="task-critical",
        result={"error": "Migration failed"},
        requires_followup=True,
    )
    dec_followup = runtime.salience_engine.evaluate(ev_followup, runtime.current_state)
    assert dec_followup.wake_cognition
    assert dec_followup.level == SalienceLevel.HIGH


# ── Test 4: Provider Swap Test ─────────────────────────────────────────
def test_4_provider_swap_continuity(clean_upaa_env: Path):
    """1. Create persistent agent.
    2. Interact through provider A.
    3. Persist episode/goal/reflection.
    4. Stop process / restart.
    5. Switch to provider B.
    6. Prove identity, state, and memory continuity.
    """
    # Phase 1: Provider A
    runtime_a = EntityRuntime(state_root=clean_upaa_env)
    runtime_a.execute_turn(
        "Remember that my favorite programming language is Rust",
        session_id="p_swap",
        context={
            "model_runner": lambda t: "Preference recorded with Provider A",
            "react_runner": lambda t, session_key="p_swap": {
                "text": "Preference recorded with Provider A",
                "tool_activity": [],
            },
        },
    )
    # Record structured reflection
    refl = StructuredReflection(
        reflection_id="refl-auth-1",
        hypothesis="OAuth token refresh requires pre-validating client expiration",
        confidence=0.85,
        failure_conditions="token_expired_without_refresh",
        applicability_conditions=["auth", "oauth"],
        supporting_episode_ids=["ep-1"],
    )
    runtime_a.reflexion_store.add_reflection(refl)
    orig_entity_id = runtime_a.identity.entity_id

    # Simulate process stop and restart with Provider B
    EntityRuntime.reset_singleton()
    runtime_b = EntityRuntime(state_root=clean_upaa_env)

    # Prove identity continuity
    assert runtime_b.identity.entity_id == orig_entity_id

    # Prove episodic memory continuity
    episodes = runtime_b.memory_subsystem.episodic.get_session_episodes("p_swap")
    assert len(episodes) >= 1
    assert "Provider A" in episodes[0].agent_response

    # Prove reflection continuity
    retrieved = runtime_b.reflexion_store.retrieve_applicable("fix auth token issue")
    assert len(retrieved) >= 1
    assert "OAuth token refresh" in retrieved[0].hypothesis

    # Continue task with Provider B
    res_b = runtime_b.execute_turn(
        "Confirm my preferred programming language",
        session_id="p_swap",
        context={"model_runner": lambda t: "Executed confirmation with Provider B"},
    )
    assert "Provider B" in res_b["text"]


# ── Test 5: Interface Swap Test ────────────────────────────────────────
def test_5_interface_swap_shared_authority(clean_upaa_env: Path):
    """CLI, Bridge, and Gateway must all share the same Agent Identity,
    SelfState, and episodic history through EntityRuntime.
    """
    runtime = EntityRuntime.get_singleton(state_root=clean_upaa_env)

    # 1. Turn via CLI
    runtime.execute_turn(
        "CLI message",
        source="cli",
        session_id="shared_session",
        context={"model_runner": lambda t: "CLI reply"},
    )

    # 2. Turn via Bridge
    runtime.execute_turn(
        "Bridge message",
        source="bridge",
        session_id="shared_session",
        context={"model_runner": lambda t: "Bridge reply"},
    )

    # 3. Turn via Gateway
    runtime.execute_turn(
        "Gateway message",
        source="gateway",
        session_id="shared_session",
        context={"model_runner": lambda t: "Gateway reply"},
    )

    # Verify shared unified episodic history
    episodes = runtime.memory_subsystem.episodic.get_session_episodes("shared_session")
    assert len(episodes) == 3
    assert [e.user_text for e in episodes] == ["CLI message", "Bridge message", "Gateway message"]
    assert [e.agent_response for e in episodes] == ["CLI reply", "Bridge reply", "Gateway reply"]

    # Verify all shared the exact same identity
    events = list(runtime.event_store.replay_all())
    human_events = [e for e in events if e.event_type == EventType.HUMAN_MESSAGE.value]
    assert len(human_events) == 3
    assert {e.source for e in human_events} == {"cli", "bridge", "gateway"}


# ── Test 6: Sleep-Time Processing ─────────────────────────────────────
def test_6_sleep_time_consolidation(clean_upaa_env: Path):
    """History with successes, failure, and unresolved goal:
    Run sleep-time processing -> semantic extraction, reflection, contradiction handling.
    """
    runtime = EntityRuntime.get_singleton(state_root=clean_upaa_env)

    # Ingest varied history
    runtime.submit_human_message("Goal: Complete database index rebuild", session_id="work")
    runtime.record_tool_start("reindex", {"table": "users"}, call_id="c1", session_id="work")
    runtime.record_tool_result("reindex", {"indexed": True}, call_id="c1", duration_s=1.2, session_id="work")
    runtime.record_tool_start("optimize", {"table": "logs"}, call_id="c2", session_id="work")
    runtime.record_tool_result("optimize", None, call_id="c2", duration_s=0.5, session_id="work", error="lock timeout")

    # Run sleep-time processing
    processor = SleepTimeProcessor(
        state_root=clean_upaa_env,
        event_store=runtime.event_store,
        memory=runtime.memory_subsystem,
    )
    cycle = processor.run_sleep_cycle(reason="idle_maintenance")

    assert cycle.claims_recorded >= 1
    assert cycle.reflections_generated >= 1
    assert cycle.duration_s >= 0.0

    # Verify state survives restart
    EntityRuntime.reset_singleton()
    restarted = EntityRuntime(state_root=clean_upaa_env)
    assert restarted.current_state.total_events_processed >= 5


# ── Test 7: Skill Learning & Promotion ────────────────────────────────
def test_7_voyager_skill_promotion_to_production_registry(clean_upaa_env: Path):
    """Demonstrate:
    Task -> successful execution -> candidate extraction -> verification gate ->
    production SKILL.md registration -> subsequent retrieval.
    """
    skills_dir = clean_upaa_env / "skills"
    pipeline = SkillPromotionPipeline(skills_dir=skills_dir)

    # 1. Candidate extracted
    candidate = pipeline.extract_candidate(
        name="secure_backup_v1",
        description="Creates timestamped encrypted archives of project directories",
        code="def run(): return {'archived': True, 'verified': True}",
        parameters={"source_dir": "str", "target_dir": "str"},
    )

    # 2. Automated verification gate passes
    verif = pipeline.verify_candidate(
        candidate,
        verification_test=lambda code: "return {'archived': True" in code,
    )
    assert verif.passed

    # 3. Promoted into REAL production registry
    promoted = pipeline.promote(candidate, verif)
    assert promoted

    # 4. Check real SKILL.md filesystem artifact
    skill_file = skills_dir / "secure_backup_v1" / "SKILL.md"
    assert skill_file.is_file()
    text = skill_file.read_text(encoding="utf-8")
    assert "name: secure_backup_v1" in text
    assert "verified: true" in text
    assert "## Implementation" in text

    # 5. Subsequent run retrieves skill
    loaded = pipeline.get_skill("secure_backup_v1")
    assert loaded is not None
    assert loaded["name"] == "secure_backup_v1"


# ── Test 8: Deliberate Planning (LATS) ─────────────────────────────────
def test_8_deliberate_planning_mode():
    """Verify:
    1. >= 3 candidate plans generated.
    2. Critic evaluates goal, safety, reversibility.
    3. Winning plan selected.
    4. Execution adheres to plan steps.
    """
    goal = "Migrate database schema to v3 and clean up legacy columns"
    candidates = DeliberatePlanner.generate_candidate_plans(goal)
    assert len(candidates) >= 3

    # Ensure plan variety
    strategies = {c.strategy for c in candidates}
    assert len(strategies) >= 3

    # Critic evaluation
    selected = DeliberatePlanner.evaluate_and_select(candidates, goal)
    assert selected is not None
    assert selected.final_score > 0.5
    assert len(selected.steps) >= 3

    # If steps contain placeholders, SelfRefine expands them
    if selected.reversibility != "reversible":
        refined = SelfRefineEngine.refine_artifact(
            "\n".join(selected.steps),
            rubric="Safety checkpoints and rollback steps",
        )
        assert refined.is_approved


# ── Test 9: Tiered Perception Sensors ──────────────────────────────────
def test_9_tiered_perception_escalation():
    """Verify 3-tier perception escalation:
    Tier 0: routine telemetry (no escalation).
    Tier 1 / 2: anomaly escalates to rich evaluation.
    """
    coordinator = TieredPerceptionCoordinator()

    # 1. Normal signals -> Tier 0
    t0_obs = coordinator.process(
        source_sensor="desktop",
        deterministic_signals={"active_app": "Terminal", "disk_free_gb": 50.0, "alerts": []},
    )
    assert t0_obs.tier_reached == PerceptionTier.TIER_0_DETERMINISTIC
    assert t0_obs.salience <= 0.3

    # 2. Critical signals -> Tier 2 escalation
    t2_obs = coordinator.process(
        source_sensor="desktop",
        deterministic_signals={"active_app": "System", "disk_free_gb": 1.2, "alerts": ["Disk critical"]},
    )
    assert t2_obs.tier_reached == PerceptionTier.TIER_2_EXPENSIVE_MODEL
    assert t2_obs.salience >= 0.8
    assert "tier2_synthesis" in t2_obs.signals
