"""Unit tests for the self-contained ARES cognitive subsystem."""

import asyncio
import os
import pytest
from pathlib import Path

from jaeger_ai.ares.belief import BeliefState, EpistemicContext
from jaeger_ai.ares.engine import ARESConfig, ARESEngine, ARESResult
from jaeger_ai.ares.intent import CognitiveIntent, IntentEngine, IntentKind, MediumType
from jaeger_ai.ares.perception import PerceptionSnapshot, RepoStatus, SensorStream, SystemTelemetry
from jaeger_ai.ares.transducers import AcousticTransducer, TransducerRegistry, VisualTransducer
from jaeger_ai.core.runtime.heartbeat import get_ares_engine, tick_ares


@pytest.fixture
def temp_ares_env(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return workspace, data_dir


def test_perception_snapshot(temp_ares_env):
    async def _run():
        workspace, _ = temp_ares_env
        sensor = SensorStream(workspace_root=workspace)
        snapshot = await sensor.perceive()

        assert isinstance(snapshot, PerceptionSnapshot)
        assert snapshot.repo.is_git is False
        assert snapshot.system.disk_total_gb >= 0.0
        assert snapshot.operator.idle_seconds >= 0.0
        data = snapshot.to_dict()
        assert "repo" in data
        assert "system" in data
        assert "operator" in data

    asyncio.run(_run())


def test_epistemic_context_retention(temp_ares_env):
    workspace, data_dir = temp_ares_env
    ctx = EpistemicContext(cache_dir=data_dir)

    # Record goals and insights
    ctx.record_goal("goal-1", "Stabilize autonomous test suite")
    ctx.add_insight("Matthew prefers concise executive summaries")

    assert len(ctx.current.active_goals) == 1
    assert ctx.current.active_goals[0].description == "Stabilize autonomous test suite"
    assert "Matthew prefers concise executive summaries" in ctx.current.recent_insights

    # Simulate reload from disk (verifying unbroken persistence)
    ctx_reloaded = EpistemicContext(cache_dir=data_dir)
    assert len(ctx_reloaded.current.active_goals) == 1
    assert "Matthew prefers concise executive summaries" in ctx_reloaded.current.recent_insights

    # Mark goal completed
    ctx_reloaded.mark_goal_completed("goal-1")
    assert ctx_reloaded.current.active_goals[0].completed is True


def test_endogenous_intent_formation():
    async def _run():
        intent_engine = IntentEngine(salience_threshold=0.5)
        belief = BeliefState()

        # 1. Normal state -> Silent Vigil
        healthy_snapshot = PerceptionSnapshot()
        intent = await intent_engine.form_intent(healthy_snapshot, belief)
        assert intent.kind == IntentKind.SILENT_VIGIL
        assert intent.is_active is False

        # 2. Critical low disk -> Urgent Broadcast
        low_disk_snapshot = PerceptionSnapshot(
            system=SystemTelemetry(disk_free_gb=2.0, disk_total_gb=500.0)
        )
        alert_intent = await intent_engine.form_intent(low_disk_snapshot, belief)
        assert alert_intent.kind == IntentKind.INSIGHT_BROADCAST
        assert alert_intent.salience >= 0.9
        assert alert_intent.is_active is True
        assert alert_intent.target_medium == MediumType.VISUAL

        # 3. High working-tree drift -> Operator Assist
        dirty_repo_snapshot = PerceptionSnapshot(
            repo=RepoStatus(is_git=True, dirty_files_count=25)
        )
        assist_intent = await intent_engine.form_intent(dirty_repo_snapshot, belief)
        assert assist_intent.kind == IntentKind.OPERATOR_ASSIST
        assert assist_intent.is_active is True
        assert assist_intent.target_medium == MediumType.MULTI_MODAL

    asyncio.run(_run())


def test_medium_transducers(temp_ares_env):
    async def _run():
        workspace, data_dir = temp_ares_env
        registry = TransducerRegistry()

        # Override visual transducer with temp events dir
        registry.register(MediumType.VISUAL, VisualTransducer(events_dir=data_dir))
        registry.register(MediumType.ACOUSTIC, AcousticTransducer(enable_audio_play=False))

        intent = CognitiveIntent(
            kind=IntentKind.INSIGHT_BROADCAST,
            goal="Test transducer broadcast",
            salience=0.85,
            emotional_valence="analytical",
            target_medium=MediumType.VISUAL,
        )

        results = await registry.broadcast(intent)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].medium == MediumType.VISUAL

        # Verify event logged to events.jsonl
        events_file = data_dir / "events.jsonl"
        assert events_file.exists()
        assert "Test transducer broadcast" in events_file.read_text(encoding="utf-8")

    asyncio.run(_run())


def test_ares_engine_tick_cycle(temp_ares_env):
    async def _run():
        workspace, data_dir = temp_ares_env
        config = ARESConfig(
            enabled=True,
            workspace_root=workspace,
            data_dir=data_dir,
            salience_threshold=0.5,
        )
        engine = ARESEngine(config=config)

        # Disable audio sound playing in acoustic transducer for test isolation
        engine.transducers.register(MediumType.ACOUSTIC, AcousticTransducer(enable_audio_play=False))

        # Run tick in clean state -> should be vigilant_idle
        res = await engine.tick()
        assert isinstance(res, ARESResult)
        assert res.status == "vigilant_idle"
        assert res.intent is not None
        assert res.intent.kind == IntentKind.SILENT_VIGIL

        # Add a pending goal and idle condition to trigger autonomous maintenance action
        engine.epistemic_context.record_goal("g-99", "Refactor core subsystems")
        engine.sensor_stream._last_user_activity_ts = 0.0  # Force idle > 300s

        res2 = await engine.tick()
        assert res2.status == "acted"
        assert res2.intent.kind == IntentKind.SYSTEM_MAINTENANCE
        assert len(res2.transductions) > 0

        # Verify cause and effect log persisted
        ce_file = data_dir / "cause_and_effect.jsonl"
        assert ce_file.exists()
        assert "Refactor core subsystems" in ce_file.read_text(encoding="utf-8")

        # Verify status report
        status = engine.status()
        assert status["enabled"] is True
        assert status["last_status"] == "acted"

    asyncio.run(_run())


def test_heartbeat_ares_hook(temp_ares_env):
    workspace, data_dir = temp_ares_env
    # Create layout-like object with root and isolation
    class MockLayout:
        root = workspace
    layout = MockLayout()

    engine = get_ares_engine(layout)
    assert engine is not None

    result = tick_ares(layout)
    assert result is not None
    assert hasattr(result, "status")
