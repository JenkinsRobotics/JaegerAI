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


def test_event_bus_handler_dag_order_and_cycle_rejection() -> None:
    import pytest
    from jaeger_events import HandlerCycleError

    bus = EventBus()
    order: list[str] = []
    # Subscribe child BEFORE parent — DAG must still execute parent first!
    bus.subscribe("turn.finish", lambda _ev: order.append("notify"), name="notify", depends_on=("persist",))
    bus.subscribe("turn.finish", lambda _ev: order.append("persist"), name="persist")
    bus.publish("turn.finish", {"ok": True})
    assert order == ["persist", "notify"]

    with pytest.raises(HandlerCycleError):
        bus.subscribe("turn.finish", lambda _ev: None, name="loop_a", depends_on=("loop_b",))
        bus.subscribe("turn.finish", lambda _ev: None, name="loop_b", depends_on=("loop_a",))


def test_fenced_event_stream_blocks_zombie_writers_and_preserves_seq_on_reopen() -> None:
    import pytest
    from jaeger_events import FencedEventStream, StaleWriterError

    stream = FencedEventStream()
    g1 = stream.open_attempt("run-1")
    e1 = stream.append("run-1", g1, "turn.start", {"step": 1})
    assert e1.seq == 1

    # New attempt supersedes g1 above floor
    g2 = stream.reopen("run-1", floor_seq=10)
    assert g2 > g1
    with pytest.raises(StaleWriterError):
        stream.append("run-1", g1, "turn.delta", {"stale": True})
    with pytest.raises(StaleWriterError):
        stream.close_attempt("run-1", g1)

    e2 = stream.append("run-1", g2, "turn.resumed", {"ok": True})
    assert e2.seq == 11
    assert [e.seq for e in stream.read_since("run-1", after_seq=1)] == [11]

    # Reset drops buffered events without rolling back monotonic seq
    stream.reset_events("run-1", g2)
    e3 = stream.append("run-1", g2, "turn.retry", {"attempt": 2})
    assert e3.seq == 12
    assert [e.seq for e in stream.read_since("run-1", after_seq=0)] == [12]


def test_live_contextvar_seam_stamps_tool_call_and_subagent() -> None:
    from jaeger_events import live

    seen: list[tuple[str, dict]] = []
    assert live.active() is False
    with live.bind(lambda ev, data: seen.append((ev, data))):
        assert live.active() is True
        with live.tool_call("tc-9"), live.subagent("sub-2"):
            live.progress("working", fraction=0.5)
    assert seen == [("tool.progress", {"message": "working", "fraction": 0.5, "call_id": "tc-9", "subagent_id": "sub-2"})]
    assert live.active() is False
