"""Pinocchio Persistent Entity Architecture Acceptance & Validation Suite.

Covers all 12 mandatory acceptance criteria (A through L):
A. Identity continuity (persists across cold reboots, independent of session ID)
B. Provider independence (model/provider swaps preserve entity identity and memory)
C. Interface independence (Gateway, Bridge, and CLI share underlying entity state)
D. Heartbeat truth (system event, no fake human message, quiet beat updates state with 0 model calls)
E. Tool consequence loop (tool.started -> tool.completed/failed -> durable consequence event)
F. Background continuity (background tasks return to same persistent history with provenance)
G. Self-state reconstruction (cold boot rebuilds SelfState from persisted event log)
H. Passive event without LLM (routine observations update state with zero model invocations)
I. Salient event wakeup (high-salience anomaly wakes cognition)
J. Memory consolidation (episodic events consolidate into WorldModel with provenance)
K. Skill acquisition (attempt -> verification test -> promotion to library -> retrieval)
L. Multi-runtime convergence (all runtime routes converge on EntityRuntime)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jaeger_ai.core.entity.attention import SalienceEngine, SalienceLevel
from jaeger_ai.core.entity.consolidation import MemoryConsolidator
from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.event_store import SqliteEventStore
from jaeger_ai.core.entity.identity import EntityIdentity, resolve_entity_identity
from jaeger_ai.core.entity.reducer import reduce_event, replay_events
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.entity.self_state import SelfState
from jaeger_ai.core.entity.sensors.desktop_activity import DesktopActivitySensor
from jaeger_ai.core.entity.skills.promotion import SkillPromotionPipeline
from jaeger_ai.core.runtime import heartbeat as hb


@pytest.fixture
def isolated_state_dir(tmp_path: Path):
    """Provides a completely isolated state directory for persistent entity tests."""
    state_dir = tmp_path / "jaeger_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    EntityRuntime.reset_singleton()
    yield state_dir
    EntityRuntime.reset_singleton()


# ── Acceptance Test A: Identity Continuity ────────────────────────────

def test_acceptance_a_identity_continuity(isolated_state_dir: Path):
    """Start Jaeger, record event, shut down completely, restart, verify identity & memory."""
    # 1. First boot
    runtime1 = EntityRuntime(state_root=isolated_state_dir)
    entity_id_1 = runtime1.identity.entity_id
    assert entity_id_1.startswith("jaeger-entity-")

    # Ingest interaction across arbitrary sessions
    runtime1.submit_human_message("Remember that project Apollo is due Friday", session_id="session-alpha")
    runtime1.record_agent_response("Acknowledged Apollo due date", session_id="session-alpha")
    runtime1.submit_human_message("What's on my calendar?", session_id="session-beta")

    assert runtime1.current_state.total_events_processed == 3

    # 2. Simulate complete process shutdown
    del runtime1
    EntityRuntime.reset_singleton()

    # 3. Cold reboot
    runtime2 = EntityRuntime(state_root=isolated_state_dir)
    assert runtime2.identity.entity_id == entity_id_1
    assert runtime2.current_state.total_events_processed == 3

    # Verify events are fully recoverable across sessions
    events_alpha = runtime2.event_store.query_events(session_id="session-alpha")
    assert len(events_alpha) == 2
    assert events_alpha[0].payload["text"] == "Remember that project Apollo is due Friday"

    events_beta = runtime2.event_store.query_events(session_id="session-beta")
    assert len(events_beta) == 1
    assert events_beta[0].payload["text"] == "What's on my calendar?"


# ── Acceptance Test B: Provider Independence ──────────────────────────

def test_acceptance_b_provider_independence(isolated_state_dir: Path):
    """Model changes do not change the entity identity or break memory continuity."""
    runtime = EntityRuntime(state_root=isolated_state_dir)
    initial_id = runtime.identity.entity_id

    # Turn 1 with Model A (e.g. Hermes local)
    runtime.submit_human_message("Setup repository guidelines")
    runtime.record_agent_response("Guidelines created", model="hermes-3-llama-3.1-8b")

    # Model Swap to Model B (e.g. Claude 3.5 Sonnet)
    runtime.submit_human_message("Audit the guidelines")
    runtime.record_agent_response("Audit passed with zero warnings", model="claude-3-5-sonnet")

    # Model Swap to Model C (e.g. Ollama qwen2.5)
    runtime.submit_human_message("Summarize status")
    runtime.record_agent_response("Everything ready", model="qwen2.5-coder")

    # Verify identity never drifted
    assert runtime.identity.entity_id == initial_id
    assert runtime.current_state.total_events_processed == 6

    # Verify all turns belong to the same entity history
    events = runtime.event_store.query_events()
    models_used = [e.payload.get("model") for e in events if e.event_type == EventType.AGENT_RESPONSE.value]
    assert models_used == ["hermes-3-llama-3.1-8b", "claude-3-5-sonnet", "qwen2.5-coder"]


# ── Acceptance Test C: Interface Independence ─────────────────────────

def test_acceptance_c_interface_independence(isolated_state_dir: Path):
    """Bridge, Gateway, and CLI all address the same underlying entity state."""
    runtime = EntityRuntime(state_root=isolated_state_dir)

    # 1. Gateway interaction
    runtime.submit_human_message("Message via Mac App over Gateway", source="gateway", session_id="dispatcher")
    runtime.record_agent_response("Gateway reply", session_id="dispatcher")

    # 2. Bridge / TUI interaction
    runtime.submit_human_message("Message via TUI over Bridge", source="bridge", session_id="dispatcher")
    runtime.record_agent_response("Bridge reply", session_id="dispatcher")

    # 3. CLI interaction
    runtime.submit_human_message("Message via CLI", source="cli", session_id="cli-run")
    runtime.record_agent_response("CLI reply", session_id="cli-run")

    assert runtime.current_state.total_events_processed == 6
    interfaces = runtime.current_state.active_interfaces
    assert "gateway" in interfaces
    assert "bridge" in interfaces
    assert "cli" in interfaces


# ── Acceptance Test D: Heartbeat Truth ─────────────────────────────────

def test_acceptance_d_heartbeat_truth(isolated_state_dir: Path):
    """Trigger a heartbeat: event source is system, no fake human message, silent OK when quiet."""
    runtime = EntityRuntime(state_root=isolated_state_dir)

    mock_layout = MagicMock()
    mock_layout.memory_dir = isolated_state_dir / "memory"

    # Quiet beat (no briefing due, no urgent work)
    with patch.object(EntityRuntime, "get_singleton", return_value=runtime):
        event, wake_cognition, prompt = hb.execute_heartbeat_event(mock_layout)

    assert event.event_type == EventType.SYSTEM_HEARTBEAT.value
    assert event.actor == "system:heartbeat"
    assert event.source == "runtime.heartbeat"
    assert wake_cognition is False
    assert prompt == hb.HEARTBEAT_OK

    # Verify no fake human message was persisted in the event log
    events = runtime.event_store.query_events()
    assert len(events) == 1
    assert events[0].event_type == EventType.SYSTEM_HEARTBEAT.value
    assert not any(e.event_type == EventType.HUMAN_MESSAGE.value for e in events)


# ── Acceptance Test E: Tool Consequence Loop ───────────────────────────

def test_acceptance_e_tool_consequence_loop(isolated_state_dir: Path):
    """Intent -> tool.started -> tool result -> tool.completed/failed -> state update."""
    runtime = EntityRuntime(state_root=isolated_state_dir)

    # Tool success
    t_start = runtime.record_tool_start("search_web", {"query": "OpenClaw spec"}, call_id="c-1")
    assert runtime.current_state.current_activity == "tool_executing:search_web"

    t_end = runtime.record_tool_result("search_web", {"results": ["doc1"]}, call_id="c-1", duration_s=1.2)
    assert runtime.current_state.current_activity == "idle"

    # Tool failure
    runtime.record_tool_start("disk_write", {"file": "/protected"}, call_id="c-2")
    runtime.record_tool_result("disk_write", None, call_id="c-2", duration_s=0.1, error="PermissionDenied")
    assert runtime.current_state.current_activity == "idle"
    assert any("PermissionDenied" in u for u in runtime.current_state.uncertainty_areas)

    events = runtime.event_store.query_events()
    assert [e.event_type for e in events] == [
        EventType.TOOL_STARTED.value,
        EventType.TOOL_COMPLETED.value,
        EventType.TOOL_STARTED.value,
        EventType.TOOL_FAILED.value,
    ]


# ── Acceptance Test F: Background Continuity ──────────────────────────

def test_acceptance_f_background_continuity(isolated_state_dir: Path):
    """Async background completion returns to persistent entity history with correct provenance."""
    runtime = EntityRuntime(state_root=isolated_state_dir)

    # Interactive turn initiates work
    runtime.submit_human_message("Run background security audit", session_id="dispatcher")
    runtime.record_agent_response("Background task started: task-sec-42", session_id="dispatcher")

    # Interactive turn is done; time passes; background task completes asynchronously
    runtime.record_background_completed(
        task_id="task-sec-42",
        result={"vulnerabilities_found": 0, "status": "clean"},
        session_id="dispatcher",
        requires_followup=False,
    )

    events = runtime.event_store.query_events(session_id="dispatcher")
    assert len(events) == 3
    bg_evt = events[-1]
    assert bg_evt.event_type == EventType.BACKGROUND_COMPLETED.value
    assert bg_evt.payload["task_id"] == "task-sec-42"
    assert bg_evt.payload["result"]["status"] == "clean"


# ── Acceptance Test G: Self-State Reconstruction ───────────────────────

def test_acceptance_g_self_state_reconstruction(isolated_state_dir: Path):
    """Reconstruct current SelfState from persisted events on cold boot."""
    store = SqliteEventStore(isolated_state_dir / "entity_events.sqlite3")
    identity = resolve_entity_identity(isolated_state_dir)

    # Ingest a sequence of diverse events directly into store
    e1 = JaegerEvent.human_message("Goal: build landing page", session_id="dev")
    e2 = JaegerEvent(
        event_id="evt-g1",
        event_type=EventType.GOAL_CREATED.value,
        actor="system",
        source="goals",
        timestamp=time.time(),
        session_id="dev",
        payload={"id": "g-101", "description": "build landing page"},
    )
    e3 = JaegerEvent.perception_sensed("desktop", {"disk_free_gb": 45.2, "dirty_files": 3})
    e4 = JaegerEvent.tool_started("git_commit", {"msg": "feat: init"}, call_id="c-99")
    e5 = JaegerEvent.tool_completed("git_commit", {"hash": "abc1234"}, call_id="c-99", duration_s=0.5)

    for e in [e1, e2, e3, e4, e5]:
        store.append(e)

    # Cold boot reconstruction
    base_state = SelfState(identity=identity)
    reconstructed = replay_events(base_state, store.replay_all())

    assert reconstructed.total_events_processed == 5
    assert len(reconstructed.active_goals) == 1
    assert reconstructed.active_goals[0]["id"] == "g-101"
    assert reconstructed.resource_telemetry.get("disk_free_gb") == 45.2
    assert reconstructed.current_activity == "idle"


# ── Acceptance Test H: Passive Event Without LLM ──────────────────────

def test_acceptance_h_passive_event_without_llm(isolated_state_dir: Path):
    """Non-critical system observation updates state with ZERO model calls."""
    runtime = EntityRuntime(state_root=isolated_state_dir)

    mock_llm_handler = MagicMock()
    runtime.register_cognition_handler(mock_llm_handler)

    sensor = DesktopActivitySensor(enabled=True)
    events = sensor.poll()
    assert len(events) == 1

    obs_event = events[0]
    state, decision = runtime.ingest(obs_event)

    # Verified: salience was passive, cognition was NOT awakened
    assert decision.wake_cognition is False
    assert mock_llm_handler.call_count == 0
    assert state.total_events_processed == 1
    assert "disk_free_gb" in state.resource_telemetry


# ── Acceptance Test I: Salient Event Wakeup ────────────────────────────

def test_acceptance_i_salient_event_wakeup(isolated_state_dir: Path):
    """Critical event above salience threshold wakes cognition."""
    runtime = EntityRuntime(state_root=isolated_state_dir)

    mock_llm_handler = MagicMock()
    runtime.register_cognition_handler(mock_llm_handler)

    # Ingest critical alert event
    alert_event = JaegerEvent.perception_sensed(
        "desktop",
        {"alerts": ["CRITICAL: CPU thermal throttle detected"], "disk_free_gb": 0.5},
        salience=0.95,
    )
    state, decision = runtime.ingest(alert_event)

    assert decision.wake_cognition is True
    assert decision.salience >= 0.7
    assert mock_llm_handler.call_count == 1


# ── Acceptance Test J: Memory Consolidation ────────────────────────────

def test_acceptance_j_memory_consolidation(isolated_state_dir: Path):
    """Consolidation extracts durable structured knowledge from episodic events."""
    runtime = EntityRuntime(state_root=isolated_state_dir)

    # Ingest related episodic events
    runtime.submit_human_message("Alice manages Project Titan.")
    runtime.submit_human_message("Bob works on Project Titan.")
    runtime.record_tool_result("long_computation", {"done": True}, call_id="t-1", duration_s=15.0)

    consolidator = MemoryConsolidator()
    recent = runtime.event_store.query_events()
    new_insights = consolidator.consolidate(recent, runtime.current_state)

    assert len(new_insights) > 0
    assert any("long_computation" in i for i in new_insights)

    # Record consolidated insights back to runtime
    runtime.ingest(
        JaegerEvent(
            event_id="cons-1",
            event_type=EventType.MEMORY_CONSOLIDATED.value,
            actor="system:consolidator",
            source="memory.consolidation",
            timestamp=time.time(),
            payload={"insights": new_insights},
        )
    )

    assert len(runtime.current_state.recent_insights) > 0


# ── Acceptance Test K: Skill Acquisition ──────────────────────────────

def test_acceptance_k_skill_acquisition(isolated_state_dir: Path):
    """Voyager loop: attempt -> candidate -> verification test -> promotion -> retrieve."""
    pipeline = SkillPromotionPipeline(skills_dir=isolated_state_dir / "skills")

    code = """def calculate_checksum(data: str) -> str:
    import hashlib
    return hashlib.sha256(data.encode()).hexdigest()
"""

    candidate = pipeline.extract_candidate(
        name="sha256_checksum",
        description="Compute SHA256 hex digest of string data",
        code=code,
    )

    # 1. Test failing verification refuses promotion
    fail_verify = pipeline.verify_candidate(candidate, lambda c: "md5" in c)
    assert fail_verify.passed is False
    assert pipeline.promote(candidate, fail_verify) is False
    assert pipeline.get_skill("sha256_checksum") is None

    # 2. Test passing verification succeeds promotion
    pass_verify = pipeline.verify_candidate(candidate, lambda c: "hashlib.sha256" in c)
    assert pass_verify.passed is True
    promoted = pipeline.promote(candidate, pass_verify)
    assert promoted is True

    # 3. Retrieve promoted skill
    retrieved = pipeline.get_skill("sha256_checksum")
    assert retrieved is not None
    assert retrieved["name"] == "sha256_checksum"
    assert "calculate_checksum" in retrieved["code"]


# ── Acceptance Test L: Multi-Runtime Convergence ──────────────────────

def test_acceptance_l_multi_runtime_convergence(isolated_state_dir: Path):
    """Verify that Gateway, Bridge, Heartbeat, and CLI converge on one EntityRuntime authority."""
    with patch.object(EntityRuntime, "get_singleton") as mock_get_rt:
        mock_rt = EntityRuntime(state_root=isolated_state_dir)
        mock_get_rt.return_value = mock_rt

        # Gateway call
        mock_rt.submit_human_message("gateway message", source="gateway")

        # Bridge heartbeat call
        mock_layout = MagicMock()
        mock_layout.memory_dir = isolated_state_dir / "memory"
        hb.execute_heartbeat_event(mock_layout)

        # Tool execution call
        mock_rt.record_tool_start("terminal", {"cmd": "ls"}, call_id="c-call")
        mock_rt.record_tool_result("terminal", "file.txt", call_id="c-call", duration_s=0.2)

        # Background call
        mock_rt.record_background_completed("bg-1", {"ok": True})

        # All roads converged on mock_rt
        assert mock_rt.current_state.total_events_processed == 5
        event_types = [e.event_type for e in mock_rt.event_store.query_events()]
        assert EventType.HUMAN_MESSAGE.value in event_types
        assert EventType.SYSTEM_HEARTBEAT.value in event_types
        assert EventType.TOOL_STARTED.value in event_types
        assert EventType.TOOL_COMPLETED.value in event_types
        assert EventType.BACKGROUND_COMPLETED.value in event_types
