"""Executable Runtime Trace & Semantic Audit Suite (UPAA Audit Verification).

Proves that:
1. Authority Ordering: Proposed Action -> Authority Layer -> Action System -> Environment.
2. Verification != Effect Ledger: Tool success does not equal objective verified.
3. Memory Taxonomy: Explicit ownership for Working, Episodic, Semantic, Reflective, and Procedural memory.
4. Executive Strategy Selection: TurnExecutive / Executive selects among 6 distinct cognitive strategies.
5. Cognition Modes: Verifies production reachability for ReAct, Planning, Reflection, Delegation.
6. Sleep-Time Processing: Heartbeat is trigger only; SleepTimeProcessor owns consolidation semantics.
7. Learning Pipeline: Verified evidence converts to durable updates across memory, world, and skills.
8. Single Runtime Authority Trace: CLI, Bridge, Gateway, Heartbeat, Background, Passive Sensor,
   and Salient Sensor all enter the same persistent EntityRuntime authority singleton.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
import pytest

from jaeger_ai.core.entity.attention import SalienceEngine
from jaeger_ai.core.entity.authority import (
    AuthorityDecision,
    AuthorityLayer,
    AuthorizationStatus,
    ProposedAction,
)
from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.event_store import SqliteEventStore
from jaeger_ai.core.entity.executive import (
    CognitiveStrategy,
    ExecutiveStrategySelector,
)
from jaeger_ai.core.entity.identity import EntityIdentity, resolve_entity_identity
from jaeger_ai.core.entity.learning import LearningPipeline, LearningTarget
from jaeger_ai.core.entity.memory import MemorySubsystem
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.entity.self_state import SelfState
from jaeger_ai.core.entity.sleep_time import (
    SleepTimeJobType,
    SleepTimeProcessor,
)
from jaeger_ai.core.entity.verification import (
    VerificationContract,
    VerificationResult,
    VerificationStatus,
)


@pytest.fixture
def clean_entity_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provides a fresh isolated directory and resets singleton."""
    state_dir = tmp_path / "jaeger_audit_state"
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


# ── Audit 1: Authority Ordering ────────────────────────────────────────

def test_audit_1_authority_ordering():
    """Prove: Proposed Action -> Authority Layer -> Action System.
    
    An unapproved action must NEVER reach the execution layer.
    """
    executed_tools: list[str] = []

    def mock_executor(tool_name: str, args: dict) -> dict:
        executed_tools.append(tool_name)
        return {"ok": True, "result": "executed"}

    # Policy that forbids destructive commands
    def safety_policy(proposal: ProposedAction) -> AuthorityDecision:
        if proposal.arguments.get("destructive"):
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason="Destructive actions forbidden without operator confirmation",
                policy_name="safety_gate",
            )
        return AuthorityDecision(status=AuthorizationStatus.APPROVED)

    authority = AuthorityLayer(policies=[safety_policy])

    # 1. Proposed Action (benign)
    action1 = ProposedAction(tool_name="read_file", arguments={"path": "notes.txt"})
    decision1 = authority.authorize(action1)
    assert decision1.is_authorized
    if decision1.is_authorized:
        mock_executor(action1.tool_name, dict(decision1.final_arguments))
    assert executed_tools == ["read_file"]

    # 2. Proposed Action (destructive)
    action2 = ProposedAction(tool_name="delete_database", arguments={"destructive": True})
    decision2 = authority.authorize(action2)
    assert not decision2.is_authorized
    assert decision2.status == AuthorizationStatus.DENIED
    if decision2.is_authorized:
        mock_executor(action2.tool_name, dict(decision2.final_arguments))
    
    # Assert executor was NEVER called for action2
    assert "delete_database" not in executed_tools
    assert len(executed_tools) == 1


# ── Audit 2: Verification ≠ Effect Ledger ─────────────────────────────

def test_audit_2_verification_distinction(tmp_path: Path):
    """Prove: Tool returned success != Objective verified."""
    test_file = tmp_path / "output.txt"

    # Case A: Tool claims success, but no independent verifier provided
    # Status MUST be OBJECTIVE_UNVERIFIED, not OBJECTIVE_VERIFIED
    res_a = VerificationContract.evaluate_tool_consequence(
        "write_file",
        {"ok": True, "bytes": 128},
        objective="Write configuration file",
    )
    assert res_a.status == VerificationStatus.OBJECTIVE_UNVERIFIED
    assert not res_a.is_verified

    # Case B: Tool claims success, but independent ground-truth disk probe finds file absent
    res_b = VerificationContract.evaluate_tool_consequence(
        "write_file",
        {"ok": True},
        objective="Write configuration file",
        external_verifier=lambda r: test_file.exists(),
    )
    assert res_b.status == VerificationStatus.OBJECTIVE_FAILED
    assert not res_b.is_verified

    # Case C: Actually create file on disk, probe verifies ground truth
    test_file.write_text("server_port=8810", encoding="utf-8")
    res_c = VerificationContract.evaluate_tool_consequence(
        "write_file",
        {"ok": True},
        objective="Write configuration file",
        external_verifier=lambda r: test_file.exists(),
    )
    assert res_c.status == VerificationStatus.OBJECTIVE_VERIFIED
    assert res_c.is_verified

    # Disk state probe with content verification
    probe_ok = VerificationContract.verify_disk_state(
        test_file,
        must_exist=True,
        content_predicate=lambda c: "server_port=8810" in c,
    )
    assert probe_ok.is_verified

    probe_mismatch = VerificationContract.verify_disk_state(
        test_file,
        must_exist=True,
        content_predicate=lambda c: "port=9999" in c,
    )
    assert probe_mismatch.status == VerificationStatus.OBJECTIVE_FAILED


# ── Audit 3: Memory Taxonomy ──────────────────────────────────────────

def test_audit_3_memory_taxonomy(clean_entity_env: Path):
    """Prove explicit ownership for Working, Episodic, Semantic, Reflective, and Procedural memory."""
    store = SqliteEventStore(clean_entity_env / "events.sqlite3")
    memory = MemorySubsystem(clean_entity_env, store)

    # 1. Working Memory (transient, turn-level)
    memory.working.set_scratch("turn_tokens", 450)
    memory.working.active_goals = ["complete_audit"]
    assert memory.working.get_scratch("turn_tokens") == 450
    assert memory.working.active_goals == ["complete_audit"]

    # 2. Episodic Memory (immutable chronological event store)
    ev = JaegerEvent.human_message("What is the status of project Pinocchio?", session_id="s1")
    persisted = memory.episodic.record_event(ev)
    assert persisted.event_id.startswith("msg-")
    history = memory.episodic.query_history(session_id="s1")
    assert len(history) == 1

    # 3. Semantic Memory (structured knowledge & world model facts)
    claim_res = memory.semantic.record_claim(
        subject="Pinocchio",
        predicate="status",
        value="audit_in_progress",
    )
    assert claim_res["predicate"] == "status"

    # 4. Reflective Memory (distilled meta-cognitive insights)
    ins = memory.reflective.store_insight(
        topic="architecture_alignment",
        observation="Separating verification from effect ledger prevents false completion",
        implication="Always require external state predicate for high-consequence tasks",
    )
    assert ins.insight_id.startswith("ins-")
    recent_insights = memory.reflective.get_recent_insights()
    assert len(recent_insights) >= 1
    assert recent_insights[0].topic == "architecture_alignment"

    # 5. Procedural Memory (verified skills & operational recipes)
    skill_file = memory.procedural.skill_dir / "git_audit.py"
    skill_file.write_text("def run_git_audit(): return True", encoding="utf-8")
    assert "git_audit" in memory.procedural.list_skills()
    assert "def run_git_audit" in memory.procedural.get_skill("git_audit")

    # Verify overall telemetry
    telem = memory.summarize_telemetry()
    assert telem["working_goals_count"] == 1
    assert telem["episodic_event_count"] == 1
    assert telem["reflective_insights_count"] >= 1
    assert telem["procedural_skills_count"] >= 1


# ── Audit 4 & 5: Executive Strategy Selection & Cognition Modes ──────

def test_audit_4_executive_strategy_selection():
    """Prove Executive selects among 6 distinct cognitive strategies."""
    base_state = SelfState(identity=EntityIdentity.create_default("test"))

    # 1. Passive / Low Salience
    ev_passive = JaegerEvent.perception_sensed("sensor", {}, salience=0.1)
    dec_passive = ExecutiveStrategySelector.select_strategy(ev_passive, base_state)
    assert dec_passive.strategy == CognitiveStrategy.PASSIVE_OBSERVE

    # 2. Direct Response — only for an EXPLICIT no-tools/text-only request.
    # A plain informational question ("what is the speed of light") is NOT
    # this case: it used to be, via a keyword classifier that denied tools
    # to anything not matching a fixed verb list, and a live operator asking
    # "what tools do you have" or "open youtube for me" got confidently told
    # neither was possible — both real capabilities the classifier just
    # never recognised the wording for (audit, 2026-09-22). Tool access is
    # now the default for a human message; DIRECT_RESPONSE is the opt-out,
    # triggered by what the request says, not by a hardcoded example phrase.
    ev_direct = JaegerEvent.human_message("Answer in text only, no tools: what is the speed of light?")
    dec_direct = ExecutiveStrategySelector.select_strategy(ev_direct, base_state)
    assert dec_direct.strategy == CognitiveStrategy.DIRECT_RESPONSE

    # 2b. The same trivia question with no opt-out phrase gets tools like any
    # other message. The model decides per turn whether it needs one — it is
    # not pre-judged unable to have one by a keyword gate.
    ev_trivia = JaegerEvent.human_message("What is the speed of light?")
    dec_trivia = ExecutiveStrategySelector.select_strategy(ev_trivia, base_state)
    assert dec_trivia.strategy == CognitiveStrategy.REACT_LOOP

    # 3. ReAct Tool Loop (Action prompt, using an action verb)
    ev_react = JaegerEvent.human_message("Create a new directory called /tmp/build and inspect it")
    dec_react = ExecutiveStrategySelector.select_strategy(ev_react, base_state)
    assert dec_react.strategy == CognitiveStrategy.REACT_LOOP

    # 3c. ReAct Tool Loop for an ordinary request sharing no vocabulary with
    # any action-verb list — the exact shape of request that fell through to
    # a tool-less turn before this fix (send an email, list your tools, open
    # a URL). Tool access must not depend on the request happening to use
    # one of a fixed set of words.
    ev_ordinary = JaegerEvent.human_message("Can you check my email and pull up my schedule?")
    dec_ordinary = ExecutiveStrategySelector.select_strategy(ev_ordinary, base_state)
    assert dec_ordinary.strategy == CognitiveStrategy.REACT_LOOP

    # 3b. Memory writes are mutating actions, not chat (live Phase 6 defect)
    ev_remember = JaegerEvent.human_message(
        "Remember that the validation project codename is Blue Lantern."
    )
    dec_remember = ExecutiveStrategySelector.select_strategy(ev_remember, base_state)
    assert dec_remember.strategy == CognitiveStrategy.REACT_LOOP

    # 4. Deliberate Planning (Batch / Goal prompt)
    ev_plan = JaegerEvent.human_message("Process these 50 records and do not stop until done")
    dec_plan = ExecutiveStrategySelector.select_strategy(ev_plan, base_state)
    assert dec_plan.strategy == CognitiveStrategy.DELIBERATE_PLANNING
    assert dec_plan.requires_work_ledger

    # 5. Specialist Delegation
    ev_del = JaegerEvent.human_message("Delegate to Codex to optimize this SQL query")
    dec_del = ExecutiveStrategySelector.select_strategy(ev_del, base_state)
    assert dec_del.strategy == CognitiveStrategy.SPECIALIST_DELEGATION
    assert dec_del.target_specialist == "codex"

    # 6. Sleep-Time Consolidation (Quiet heartbeat)
    ev_hb = JaegerEvent.heartbeat(payload={"quiet": True})
    dec_hb = ExecutiveStrategySelector.select_strategy(ev_hb, base_state)
    assert dec_hb.strategy == CognitiveStrategy.SLEEP_TIME_CONSOLIDATION


# ── Audit 6: Sleep-Time Processing ────────────────────────────────────

def test_audit_6_sleep_time_processing(clean_entity_env: Path):
    """Prove heartbeat is a trigger only; SleepTimeProcessor owns processing semantics."""
    store = SqliteEventStore(clean_entity_env / "events.sqlite3")
    processor = SleepTimeProcessor(clean_entity_env, store)

    # Ingest a failed tool event into episodic store
    store.append(JaegerEvent.tool_failed("failing_tool", "timeout", call_id="c1", duration_s=1.0))

    # Heartbeat triggers sleep cycle
    cycle_result = processor.run_sleep_cycle(
        reason="heartbeat_idle_trigger",
        job_types=[SleepTimeJobType.CONSOLIDATION, SleepTimeJobType.REFLECTION],
    )

    assert cycle_result.cycle_id.startswith("sleep-")
    assert "consolidation" in cycle_result.jobs_executed
    assert "reflection" in cycle_result.jobs_executed
    assert cycle_result.reflections_generated >= 1

    # Verify memory.consolidated event persisted to Event Fabric
    events = store.query_events(event_type=EventType.MEMORY_CONSOLIDATED.value)
    assert len(events) == 1
    assert events[0].payload["reason"] == "heartbeat_idle_trigger"


# ── Audit 7: Learning Pipeline ────────────────────────────────────────

def test_audit_7_learning_pipeline(clean_entity_env: Path):
    """Prove Learning converts verified experience into durable updates."""
    store = SqliteEventStore(clean_entity_env / "events.sqlite3")
    pipeline = LearningPipeline(clean_entity_env, store)
    state = SelfState(identity=EntityIdentity.create_default("test"))

    # Turn event with verified objective
    ev_success = JaegerEvent.tool_completed("git_commit", {"status": "ok"}, call_id="c2", duration_s=0.5)
    verif_ok = VerificationResult(
        status=VerificationStatus.OBJECTIVE_VERIFIED,
        target_objective="Commit git repository",
        evidence="git log confirms commit 77c612ea on pinocchio",
        verifier="git_probe",
    )

    dec_success = pipeline.process_experience(ev_success, verif_ok, state)
    assert LearningTarget.EPISODIC in dec_success.targets
    assert LearningTarget.SEMANTIC in dec_success.targets
    assert LearningTarget.WORLD_MODEL in dec_success.targets
    assert LearningTarget.STRATEGY_METADATA in dec_success.targets
    assert dec_success.updates_applied["strategy_confidence"] == "reinforced"

    # Turn event with failed objective
    ev_fail = JaegerEvent.tool_completed("git_push", {"ok": True}, call_id="c3", duration_s=0.5)
    verif_fail = VerificationResult(
        status=VerificationStatus.OBJECTIVE_FAILED,
        target_objective="Push branch to remote",
        evidence="Remote repository refused branch",
        verifier="git_probe",
        error="RemoteRejected",
    )

    dec_fail = pipeline.process_experience(ev_fail, verif_fail, state)
    assert LearningTarget.REFLECTIVE in dec_fail.targets
    assert dec_fail.updates_applied["strategy_confidence"] == "penalized"


# ── Audit 9: Single Runtime Authority Executable Trace ────────────────

def test_audit_9_single_runtime_authority_trace(clean_entity_env: Path, monkeypatch: pytest.MonkeyPatch):
    """Prove all 7 entry points converge into the identical EntityRuntime singleton instance
    through their REAL production entrypoints:
    
    1. CLI: _run_turn / run_command
    2. Bridge: run_for_voice
    3. Gateway: _execute_turn
    4. System heartbeat: execute_heartbeat_event
    5. Background completion: record_background_completed
    6. Passive sensor observation: SensorSupervisor.poll_once
    7. Salient sensor observation: SensorSupervisor.poll_once (escalated Tier 2)
    """
    import asyncio
    from jaeger_ai.main import _run_turn, run_for_voice
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.runtime.heartbeat import execute_heartbeat_event
    from jaeger_ai.core.entity.sensors.desktop_activity import DesktopActivitySensor
    from jaeger_ai.core.entity.sensors.supervisor import SensorSupervisor

    runtime = EntityRuntime.get_singleton(clean_entity_env)
    initial_entity_id = runtime.identity.entity_id

    # Mock low-level ReAct loop output so test runs offline without live local model
    monkeypatch.setattr(
        "jaeger_ai.main._run_subordinate_react",
        lambda client, text, **kw: {"text": f"Executed subordinate ReAct: {text[:30]}", "tool_activity": []},
    )

    # 1. Real CLI human message: _run_turn
    cli_result = _run_turn(
        None,
        "CLI user command: check status",
        session_key="cli-term",
        request_id="cli-req-1",
    )
    assert cli_result.get("text")
    cli_events = [e for e in runtime.event_store.replay_all() if e.source == "main._run_turn"]
    assert len(cli_events) == 1
    ev1 = cli_events[0]
    assert ev1.payload.get("text") == "CLI user command: check status"

    # 2. Real Bridge human message: run_for_voice
    bridge_result = run_for_voice(
        None,
        "Bridge client prompt: generate report",
        session_key="bridge-turn-1",
        request_id="bridge-req-1",
    )
    assert bridge_result.get("text")
    bridge_events = [e for e in runtime.event_store.replay_all() if e.session_id == "bridge-turn-1" and e.event_type == EventType.HUMAN_MESSAGE.value]
    assert len(bridge_events) == 1
    ev2 = bridge_events[0]
    assert ev2.payload.get("text") == "Bridge client prompt: generate report"

    # 3. Real Gateway human message: _execute_turn
    gw_store = GatewaySessionStore(clean_entity_env / "gw_sessions.sqlite3")
    gw_app = JaegerGatewayApp(store=gw_store)
    async def _mock_native_lead(session_id, text, **kwargs):
        return ("Gateway turn executed via native lead", "mcp:127.0.0.1:8811")
    monkeypatch.setattr(gw_app, "_native_lead_turn", _mock_native_lead)
    gw_store.ensure_session("gw-client-8810")
    gw_store.admit_request("gw-client-8810", "Gateway client: start server", request_id="gw-req-1")

    asyncio.run(gw_app._execute_turn(
        "gw-client-8810",
        "turn-gw-1",
        "Gateway client: start server",
        request_id="gw-req-1",
    ))
    gw_events = [e for e in runtime.event_store.replay_all() if e.source == "gateway" and e.event_type == EventType.HUMAN_MESSAGE.value]
    assert len(gw_events) == 1
    ev3 = gw_events[0]
    assert ev3.payload.get("text") == "Gateway client: start server"

    # 4. Real System heartbeat: execute_heartbeat_event
    class DummyLayout:
        root = clean_entity_env
        state_dir = clean_entity_env
        run_dir = clean_entity_env
        heartbeat_state_file = clean_entity_env / "heartbeat.json"
    ev4, wake, hb_text = execute_heartbeat_event(DummyLayout())
    assert ev4.event_type == EventType.SYSTEM_HEARTBEAT.value

    # 5. Real Background completion: record_background_completed
    ev5 = runtime.record_background_completed("task-bg-99", {"artifacts_written": 3}, requires_followup=False)
    assert ev5.event_type == EventType.BACKGROUND_COMPLETED.value

    # 6. Real Passive sensor observation: SensorSupervisor.poll_once (low salience)
    sensor = DesktopActivitySensor(workspace_path=str(clean_entity_env), enabled=True)
    supervisor = SensorSupervisor(runtime=runtime, sensor=sensor, enabled=True)
    ev6 = supervisor.poll_once()
    assert ev6 is not None
    assert ev6.event_type == EventType.PERCEPTION_SENSED.value
    assert ev6.salience <= 0.3

    # 7. Real Salient sensor observation: SensorSupervisor.poll_once (high salience)
    class AnomalySensor(DesktopActivitySensor):
        def poll(self):
            return [JaegerEvent.perception_sensed(
                sensor="desktop_activity",
                signals={"active_app": "CrashReporter", "alerts": ["Critical disk failure"], "disk_free_gb": 0.5},
                salience=0.85,
            )]
    salient_supervisor = SensorSupervisor(
        runtime=runtime,
        sensor=AnomalySensor(enabled=True),
        enabled=True,
    )
    ev7 = salient_supervisor.poll_once()
    assert ev7 is not None
    assert ev7.salience >= 0.85

    # Verify that get_singleton() returns the exact same object reference
    assert EntityRuntime.get_singleton() is runtime

    # Verify that NO duplicate human messages exist for any entry point
    all_human_messages = [e for e in runtime.event_store.replay_all() if e.event_type == EventType.HUMAN_MESSAGE.value]
    assert len(all_human_messages) == 3
    assert {e.session_id for e in all_human_messages} == {"cli-term", "bridge-turn-1", "gw-client-8810"}

    # Verify all events belong to the exact same EntityIdentity
    assert runtime.current_state.identity.entity_id == initial_entity_id
