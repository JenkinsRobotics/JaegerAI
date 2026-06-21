"""AgentBridge — the host-owned bus↔turn bridge (GUI-agnostic chat seam).

Validates the chat round-trip over the chassis InProcBus with an injected
fake turn function — no model, no GUI. The bridge is NOT a chassis Node;
it has a small host-component contract (start/stop/join/health).
"""

from __future__ import annotations

import queue
import time

import pytest

from jaeger_os.agent.loop.bridge import AgentBridge
from jaeger_os.app.bus.inproc import InProcBus
from jaeger_os.core.messages import ChatMessage, ChatReply


def _bridge(bus: InProcBus, **kw) -> AgentBridge:
    b = AgentBridge(bus=bus, **kw)
    b.start()
    return b


def _stop(b: AgentBridge, bus: InProcBus) -> None:
    b.stop()
    b.join(timeout=2.0)
    bus.close()


def test_chat_round_trip_echoes_reply() -> None:
    bus = InProcBus()
    replies: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))
    b = _bridge(bus, client=object(),
                run_turn=lambda c, t, session_key=None: {"text": f"echo: {t}",
                                                         "error": None})
    try:
        bus.publish(ChatMessage(text="hello"))
        assert replies.get(timeout=3.0) == "echo: hello"
        assert b.turns == 1
    finally:
        _stop(b, bus)


def test_blank_input_is_ignored() -> None:
    bus = InProcBus()
    replies: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))
    b = _bridge(bus, run_turn=lambda *a, **k: {"text": "x"})
    try:
        bus.publish(ChatMessage(text="   "))
        with pytest.raises(queue.Empty):
            replies.get(timeout=0.5)
        assert b.turns == 0
    finally:
        _stop(b, bus)


def test_turn_error_surfaces_without_killing_bridge() -> None:
    bus = InProcBus()
    replies: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))

    def boom(c, t, session_key=None):
        raise RuntimeError("model exploded")

    b = _bridge(bus, run_turn=boom)
    try:
        bus.publish(ChatMessage(text="hi"))
        reply = replies.get(timeout=3.0)
        assert "turn failed" in reply and "RuntimeError" in reply
        h = b.health()
        assert h["last_error"] and "RuntimeError" in h["last_error"]
    finally:
        _stop(b, bus)


def test_agent_error_field_is_reported() -> None:
    bus = InProcBus()
    replies: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))
    b = _bridge(bus,
                run_turn=lambda *a, **k: {"text": "", "error": "ctx overflow"})
    try:
        bus.publish(ChatMessage(text="hi"))
        assert "agent error: ctx overflow" in replies.get(timeout=3.0)
    finally:
        _stop(b, bus)


def test_health_exposes_observability() -> None:
    bus = InProcBus()
    b = _bridge(bus, run_turn=lambda *a, **k: {"text": "ok"})
    try:
        h = b.health()
        assert set(h) >= {"state", "turns", "queue_depth", "turn_active",
                          "last_error"}
        assert h["turns"] == 0
        assert h["turn_active"] is False
    finally:
        _stop(b, bus)


def test_bounded_inbox_emits_busy_when_full() -> None:
    """A size-1 inbox + a slow turn: a third message overflows and the
    bridge replies 'busy' rather than queueing unbounded work."""
    bus = InProcBus()
    replies: "queue.Queue[str]" = queue.Queue()
    started: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))

    def slow(c, t, session_key=None):
        started.put(t)
        time.sleep(0.6)
        return {"text": f"done: {t}"}

    b = _bridge(bus, run_turn=slow, max_queue=1)
    try:
        bus.publish(ChatMessage(text="first"))     # worker takes it
        started.get(timeout=2.0)                    # worker now busy on "first"
        bus.publish(ChatMessage(text="second"))     # fills the size-1 queue
        bus.publish(ChatMessage(text="third"))      # overflow -> busy reply
        seen: list[str] = []
        deadline = time.time() + 3.0
        while time.time() < deadline and not any("busy" in s for s in seen):
            try:
                seen.append(replies.get(timeout=0.2))
            except queue.Empty:
                pass
        assert any("busy" in s for s in seen), seen
    finally:
        _stop(b, bus)
