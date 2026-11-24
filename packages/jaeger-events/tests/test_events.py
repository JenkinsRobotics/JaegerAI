"""Standalone unit & contract tests for jaeger-events."""

from __future__ import annotations

import threading
import time

from jaeger_contracts import EventBusPort, EventEnvelope
from jaeger_events import (
    EventBus,
    SpanRecord,
    StreamingDeltaBatcher,
    TelemetryEmitter,
    TraceContext,
    is_replaying,
)


def test_event_bus_satisfies_protocol_and_replay_guard() -> None:
    bus = EventBus()
    assert isinstance(bus, EventBusPort)

    live_seen: list[int] = []
    side_effect_seen: list[int] = []
    replay_flags: list[bool] = []

    bus.subscribe("turn.done", lambda ev: (live_seen.append(ev.seq), replay_flags.append(is_replaying())))
    bus.subscribe("turn.done", lambda ev: side_effect_seen.append(ev.seq), skip_on_replay=True)

    e1 = bus.publish("turn.done", {"ok": True}, session_id="s1")
    e2 = bus.publish("turn.done", {"ok": True}, session_id="s1")
    assert (e1.seq, e2.seq) == (1, 2)
    assert side_effect_seen == [1, 2]
    assert replay_flags == [False, False]

    replayed = bus.replay("s1", since_seq=0)
    assert replayed == 2
    assert live_seen == [1, 2, 1, 2]
    assert replay_flags == [False, False, True, True]
    # Side-effect listener MUST NOT fire during replay
    assert side_effect_seen == [1, 2]


def test_event_bus_isolates_crashing_listener() -> None:
    bus = EventBus()
    ok_seen: list[str] = []

    def bad(_ev: EventEnvelope) -> None:
        raise RuntimeError("boom")

    bus.subscribe("x", bad)
    bus.subscribe("x", lambda ev: ok_seen.append(ev.event_type))
    bus.publish("x", {})

    assert ok_seen == ["x"]
    assert bus.listener_errors == 1


def test_streaming_delta_batcher_flushes_before_durable_frame() -> None:
    emitted: list[tuple[str, dict]] = []
    batcher = StreamingDeltaBatcher(lambda kind, data: emitted.append((kind, dict(data))), max_buffer_chars=100)

    batcher.push_delta("s1", "text", "Hello ")
    batcher.push_delta("s1", "text", "Jaeger")
    assert emitted == []  # buffered

    durable_ev = EventEnvelope(seq=1, event_type="tool.call", payload={"tool": "shell"}, session_id="s1")
    batcher.push_durable(durable_ev)

    assert [k for k, _ in emitted] == ["delta.batch", "tool.call"]
    assert emitted[0][1]["text"] == "Hello Jaeger"


def test_trace_context_w3c_roundtrip_and_non_blocking_emitter() -> None:
    root = TraceContext.new_root()
    child = root.child_span()
    assert child.trace_id == root.trace_id
    assert child.span_id != root.span_id

    parsed = TraceContext.from_traceparent(child.to_traceparent())
    assert parsed == child

    received: list[SpanRecord] = []
    gate = threading.Event()
    emitter = TelemetryEmitter(lambda rec: (received.append(rec), gate.set()), max_queue=16)
    try:
        assert emitter.emit(SpanRecord(name="tool.shell", trace_id=child.trace_id, span_id=child.span_id))
        assert gate.wait(timeout=1.5)
        emitter.flush()
    finally:
        emitter.close()

    assert len(received) == 1
    assert received[0].name == "tool.shell"
    assert emitter.delivered == 1
