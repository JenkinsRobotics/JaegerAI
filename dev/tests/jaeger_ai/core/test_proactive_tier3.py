"""Deterministic Tier 3 sensor, salience, and delivery contracts."""
from __future__ import annotations

import json
import pathlib
import time

import pytest

from jaeger_ai.core.gateway.event_bus import EVENT_TYPES
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.runtime.salience import SalienceClassifier, SalienceLevel
from jaeger_ai.core.runtime.sensor_bus import (
    HostTelemetryObserver,
    SensorBus,
    SensorEvent,
    WorkspaceObserver,
    sensor_prompt,
)


def test_notification_is_a_first_class_gateway_event() -> None:
    assert "notification.proactive" in EVENT_TYPES


def test_sensor_event_contract_and_identity() -> None:
    event = SensorEvent(
        source="workspace", kind="test_failed", summary="one test failed",
        details={"tests": ["x"]}, timestamp=1.0,
    )
    same = SensorEvent(
        source="workspace", kind="test_failed", summary="one test failed",
        details={"tests": ["x"]}, timestamp=2.0,
    )
    assert event.source == "workspace"
    assert event.kind == "test_failed"
    assert event.summary == "one test failed"
    assert event.details == {"tests": ["x"]}
    assert event.timestamp == 1.0
    assert event.identity == same.identity
    assert "Summary" in sensor_prompt(event)


def test_background_producer_submits_immediate_sensor_turn(tmp_path: pathlib.Path) -> None:
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, ModelConfig
    from jaeger_ai.core.runtime.background_producers import BackgroundProducers
    from jaeger_ai.core.runtime.sensor_bus import sensor_prompt as prompt

    class _Sink:
        def __init__(self) -> None:
            self.turns = []
        def current_tier(self):
            return "jaeger"
        def is_busy(self):
            return False
        def last_user_quiet_s(self):
            return 0.0
        def last_user_session(self):
            return "s1"
        def submit_turn(self, prompt, *, session, request_id, source, salience=None):
            self.turns.append((prompt, session, request_id, source, salience))
            return {"text": "done", "status": "completed"}

    root = tmp_path / "instance"
    root.mkdir()
    (root / "workspace").mkdir()
    cfg = Config(instance_name="test", model=ModelConfig(model_path="/dev/null"))
    cfg.automation.interaction_tier = "jaeger"
    producers = BackgroundProducers(InstanceLayout(root=root), _Sink())
    telemetry = [
        {"disk_free_gb": 5.0, "memory_pressure_level": 1},
        {"disk_free_gb": 5.0, "memory_pressure_level": 1},
    ]
    producers.sensor_bus = SensorBus(
        root / "workspace", interval_s=5, debounce_s=1, telemetry=lambda: telemetry.pop(0),
        journal_sink=lambda _event: None, model_evaluator=lambda _event: SalienceLevel.IMMEDIATE,
    )
    producers._sensor_action(cfg)
    (root / "workspace" / "notes.md").write_text("hello", encoding="utf-8")
    producers._sensor_action(cfg)  # workspace change journals, host stays quiet
    producers.sensor_bus.poll_once()
    producers._sensor_action(cfg)  # low disk transition is the immediate candidate
    assert len(producers.sink.turns) == 1
    prompt_text, session, request_id, source, salience = producers.sink.turns[0]
    assert prompt_text == prompt(producers.sensor_bus.journals()[0]) or prompt_text.startswith("A Jaeger Tier 3")
    assert session == "s1"
    assert request_id.startswith("sensor:host:disk_low:")
    assert source == "sensor"
    assert salience == "immediate"


def test_workspace_observer_debounces_and_classifies_changes(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    observer = WorkspaceObserver(root, debounce_s=8.0)
    assert observer.poll(1000.0) == []  # initial state is seeded, never announced

    autosave = root / "notes.autosave"
    autosave.write_text("draft", encoding="utf-8")
    events = observer.poll(1001.0)
    # Workspace changes are visible but restraint makes normal edits quiet;
    # autosaves are explicitly noise.
    assert [event.kind for event in events] == ["file_added"]
    assert SalienceClassifier().classify(events[0]) is SalienceLevel.NOISE
    assert observer.poll(1003.0) == []

    autosave.write_text("draft2", encoding="utf-8")
    changed = observer.poll(1010.0)
    assert [event.kind for event in changed] == ["file_changed"]
    assert SalienceClassifier().classify(changed[0]) is SalienceLevel.NOISE
    autosave.write_text("draft3", encoding="utf-8")  # same size; same event identity
    assert observer.poll(1011.0) == []  # same identity stays debounced


def test_workspace_test_failure_is_immediate(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    pytest_cache = root / ".pytest_cache" / "v" / "cache"
    pytest_cache.mkdir(parents=True)
    pytest_cache.joinpath("lastfailed").write_text("{}", encoding="utf-8")
    observer = WorkspaceObserver(root, debounce_s=8.0)
    assert observer.poll(100.0) == []

    (root / "app.py").write_text("print('x')", encoding="utf-8")
    pytest_cache.joinpath("lastfailed").write_text(
        json.dumps({"dev/tests/app.py::test_it": True}), encoding="utf-8"
    )
    events = observer.poll(101.0)
    failed = [event for event in events if event.kind == "test_failed"]
    assert len(failed) == 1
    assert failed[0].details["tests"] == ["dev/tests/app.py::test_it"]
    assert SalienceClassifier().classify(failed[0]) is SalienceLevel.IMMEDIATE


def test_workspace_test_log_failure_is_immediate(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    observer = WorkspaceObserver(root, debounce_s=8.0)
    assert observer.poll(0.0) == []
    log = root / "test-run.log"
    log.write_text("FAILED tests/app.py::test_it", encoding="utf-8")
    events = observer.poll(1.0)
    failed = [event for event in events if event.kind == "test_failed"]
    assert len(failed) == 1
    assert failed[0].details["path"] == "test-run.log"
    assert SalienceClassifier().classify(failed[0]) is SalienceLevel.IMMEDIATE


def test_workspace_branch_change_is_digest_staged(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "workspace"
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    git_dir.joinpath("HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    observer = WorkspaceObserver(root, debounce_s=8.0)
    assert observer.poll(0.0) == []
    git_dir.joinpath("HEAD").write_text("ref: refs/heads/release\n", encoding="utf-8")
    events = observer.poll(1.0)
    assert [event.kind for event in events] == ["branch_changed"]
    assert events[0].details["to"] == "release"
    assert SalienceClassifier().classify(events[0]) is SalienceLevel.DIGEST


def test_host_telemetry_transitions_and_critical_salience() -> None:
    readings = [
        {"disk_free_gb": 50.0, "memory_pressure_level": 1, "battery_level": 90.0},
        {"disk_free_gb": 10.0, "memory_pressure_level": 1, "battery_level": 90.0},
        {"disk_free_gb": 10.0, "memory_pressure_level": 1, "battery_level": 90.0},
        {"disk_free_gb": 50.0, "memory_pressure_level": 1, "battery_level": 90.0},
    ]
    observer = HostTelemetryObserver(telemetry=lambda: readings.pop(0))
    assert observer.poll(0.0) == []
    first = observer.poll(1.0)
    assert [event.kind for event in first] == ["disk_low"]
    assert observer.poll(2.0) == []  # no repeated alarm while still low
    assert observer.poll(3.0) == []  # recovery resets the transition

    readings.append({"disk_free_gb": 8.0, "memory_pressure_level": 3, "battery_level": 90.0})
    alarm = observer.poll(4.0)
    assert [event.kind for event in alarm] == ["disk_low", "memory_pressure"]
    for event in alarm:
        assert SalienceClassifier().classify(event) is SalienceLevel.IMMEDIATE


def test_salience_filter_restraint_and_urgency() -> None:
    classifier = SalienceClassifier(model_evaluator=lambda _event: SalienceLevel.IMMEDIATE)
    assert classifier.classify(SensorEvent(
        source="workspace", kind="file_changed", summary="notes.autosave",
        details={"path": "notes.autosave"}, timestamp=1.0,
    )) is SalienceLevel.NOISE
    assert classifier.classify(SensorEvent(
        source="workspace", kind="file_changed", summary="report.md",
        details={"path": "report.md"}, timestamp=1.0,
    )) is SalienceLevel.JOURNAL
    assert classifier.classify(SensorEvent(
        source="workspace", kind="test_failed", summary="suite failed",
        details={"tests": ["test_x"]}, timestamp=1.0,
    )) is SalienceLevel.IMMEDIATE
    assert classifier.classify(SensorEvent(
        source="workspace", kind="long_task_completed", summary="durable task finished",
        details={"task_id": "t1"}, timestamp=1.0,
    )) is SalienceLevel.IMMEDIATE
    # The model fallback is exercised only for unknown kinds.
    assert classifier.classify(SensorEvent(
        source="external", kind="ambiguous", summary="unknown change",
        details={}, timestamp=1.0,
    )) is SalienceLevel.IMMEDIATE
    assert SalienceClassifier(
        model_evaluator=lambda _event: (_ for _ in ()).throw(RuntimeError("offline")),
    ).classify(SensorEvent(
        source="external", kind="ambiguous", summary="unknown change",
        details={}, timestamp=1.0,
    )) is SalienceLevel.JOURNAL


def test_sensor_bus_routes_digest_journal_and_immediate(tmp_path: pathlib.Path) -> None:
    journals: list[SensorEvent] = []
    readings = [
        {"disk_free_gb": 50.0, "memory_pressure_level": 1},
        {"disk_free_gb": 50.0, "memory_pressure_level": 1},
        {"disk_free_gb": 5.0, "memory_pressure_level": 1},
    ]
    bus = SensorBus(
        tmp_path,
        interval_s=5, debounce_s=1,
        telemetry=lambda: readings.pop(0),
        journal_sink=journals.append,
        model_evaluator=lambda _event: SalienceLevel.IMMEDIATE,
    )
    bus.poll_once()  # initial state seeds; no observations
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    bus.poll_once()
    assert bus.next_action() is None
    assert len(journals) == 1  # ordinary file changes do not wake the operator

    (tmp_path / "notes.md").write_text("changed", encoding="utf-8")
    bus.poll_once()
    candidate = bus.next_action()
    assert candidate is not None
    assert candidate.level is SalienceLevel.IMMEDIATE
    assert candidate.event.kind == "disk_low"


@pytest.mark.asyncio
async def test_gateway_rejects_sensor_turns_outside_jaeger(tmp_path: pathlib.Path) -> None:
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    app = JaegerGatewayApp(store=store)
    for tier in ("agent", "chat"):
        app._current_tier = lambda tier=tier: tier
        result = await app._run_background_turn(
            "sensor prompt", session_id="s", request_id=f"r-{tier}",
            source="sensor", salience="immediate",
        )
        assert result["status"] == "disabled"
        assert "requires 'jaeger' mode" in result["error"]
        assert store.get_request(f"r-{tier}") is None


@pytest.mark.asyncio
async def test_jaeger_immediate_sensor_turn_emits_proactive_sse(
    tmp_path: pathlib.Path,
) -> None:
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    app = JaegerGatewayApp(store=store)
    app._current_tier = lambda: "jaeger"
    rid = "sensor:workspace:test_failed:abc123"
    events: list[tuple[str, str, dict]] = []
    app.event_bus.publish = lambda session_id, event, data: events.append(
        (session_id, event, data)
    )

    async def execute_turn(
        session_id: str, turn_id: str, _text: str, *, request_id: str,
        execution: dict | None = None,
    ) -> None:
        app._persist_terminal(
            request_id, session_id, "completed",
            {
                "output": "The suite failed because fixture X is missing.",
                "status": "completed",
                "turn_id": turn_id,
                "proactive": True,
                "proactive_source": "sensor",
                "proactive_salience": "immediate",
            },
            assistant_text="The suite failed because fixture X is missing.",
            record_entity_event=False,
        )

    app._execute_turn = execute_turn
    result = await app._run_background_turn(
        sensor_prompt(SensorEvent(
            source="workspace", kind="test_failed", summary="suite failed",
            details={"tests": ["test_x"]}, timestamp=time.time(),
        )),
        session_id="s1", request_id=rid, source="sensor", salience="immediate",
    )
    assert result["error"] is None
    assert store.get_request(rid)["execution"]["options"]["proactive_salience"] == "immediate"
    notification = [data for _, event, data in events if event == "notification.proactive"]
    assert len(notification) == 1
    payload = notification[0]
    assert payload["session_id"] == "s1"
    assert payload["salience"] == "immediate"
    assert payload["speak"] is True
    assert payload["audio_cue"] == "chime"
    messages = store.get_session("s1")["messages"]
    assert "fixture X is missing" in messages[-1]["content"]


def test_salience_normalizes_to_one_wire_spelling() -> None:
    from jaeger_ai.core.gateway.server import _normalize_salience

    # IntEnum str() is the digit on 3.11+; the wire spelling must be the name.
    assert _normalize_salience(3) == "immediate"
    assert _normalize_salience(SalienceLevel.IMMEDIATE) == "immediate"
    assert _normalize_salience("IMMEDIATE") == "immediate"
    assert _normalize_salience(" digest ") == "digest"
    assert _normalize_salience(None) == "digest"
    assert _normalize_salience("bogus") == "digest"
    assert _normalize_salience(99) == "digest"


def test_sensor_fault_does_not_starve_the_idle_tick(tmp_path, monkeypatch) -> None:
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import (
        Config, HeartbeatConfig, ModelConfig, WebhookConfig,
    )
    from jaeger_ai.core.runtime import task_liveness
    from jaeger_ai.core.runtime.background_producers import BackgroundProducers

    class _Sink:
        def current_tier(self):
            return "jaeger"
        def is_busy(self):
            return False
        def last_user_quiet_s(self):
            return 10_000.0
        def last_user_session(self):
            return "s1"
        def submit_turn(self, *_a, **_k):
            raise AssertionError("no turn expected")

    class _BrokenBus:
        started = True
        def poll_once(self):
            raise RuntimeError("sensor exploded")
        def stop(self):
            pass

    reclaimed: list[object] = []
    monkeypatch.setattr(task_liveness, "reclaim_stale", reclaimed.append)
    lay = InstanceLayout(root=tmp_path / "inst")
    lay.ensure_dirs()
    cfg = Config(
        instance_name="inst", model=ModelConfig(model_path="/dev/null"),
        heartbeat=HeartbeatConfig(enabled=False), webhooks=WebhookConfig(enabled=False),
    )
    producers = BackgroundProducers(lay, _Sink())
    producers.sensor_bus = _BrokenBus()
    producers._idle_once(cfg)
    assert reclaimed == [lay]
