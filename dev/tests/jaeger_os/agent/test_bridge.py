"""AgentBridge — the host-owned bus↔turn bridge (GUI-agnostic chat seam).

Validates the chat round-trip over the chassis InProcBus with an injected
fake turn function — no model, no GUI. The bridge is NOT a chassis Node;
it has a small host-component contract (start/stop/join/health).
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

import jaeger_os.agent.loop.bridge as bridge_mod
from jaeger_os.agent.loop.bridge import AgentBridge
from jaeger_os.transport import InProcBus, topics
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


# ── transcript collision guard (0.8 U3): partials ignored, final taken ──


def test_partial_transcript_is_ignored() -> None:
    """A voice partial (is_final=False) must NOT become a chat turn —
    the audio_session node streams several of these per utterance before
    the final; treating each as a turn would fire once per fragment."""
    bus = InProcBus()
    replies: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))
    b = _bridge(bus, run_turn=lambda c, t, session_key=None: {"text": f"echo: {t}"})
    try:
        bus.publish(topics.Transcript(text="hel", is_final=False))
        bus.publish(topics.Transcript(text="hello wor", is_final=False))
        with pytest.raises(queue.Empty):
            replies.get(timeout=0.5)
        assert b.turns == 0
    finally:
        _stop(b, bus)


def test_final_transcript_becomes_a_chat_turn() -> None:
    """The final transcript (default is_final=True) drives a real turn,
    tagged with source 'voice' into the same inbox as chat."""
    bus = InProcBus()
    replies: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))
    b = _bridge(bus, run_turn=lambda c, t, session_key=None: {"text": f"echo: {t}"})
    try:
        bus.publish(topics.Transcript(text="hello world", is_final=True))
        assert replies.get(timeout=3.0) == "echo: hello world"
        assert b.turns == 1
    finally:
        _stop(b, bus)


# ── follow-up messages steer the live turn (not queued for next) ────

def test_followup_during_turn_steers_instead_of_queuing(monkeypatch) -> None:
    """A message arriving mid-turn is routed to the active agent's steer()
    (lands as guidance in the running turn), not queued as a new turn."""
    bus = InProcBus()
    steered: "queue.Queue[str]" = queue.Queue()
    monkeypatch.setattr(bridge_mod, "_steer_active_turn",
                        lambda text: (steered.put(text), True)[1])
    started: "queue.Queue[str]" = queue.Queue()
    release = threading.Event()

    def slow(c, t, session_key=None):
        started.put(t)
        release.wait(2.0)
        return {"text": f"done: {t}"}

    b = _bridge(bus, run_turn=slow)
    try:
        bus.publish(ChatMessage(text="first"))
        started.get(timeout=2.0)                 # worker busy → _turn_active set
        bus.publish(ChatMessage(text="actually use metric"))
        assert steered.get(timeout=2.0) == "actually use metric"
        release.set()
        time.sleep(0.2)
        assert b.health()["queue_depth"] == 0    # steered, not queued
    finally:
        release.set()
        _stop(b, bus)
    assert b.turns == 1                           # one turn, steered mid-flight


def test_followup_falls_back_to_queue_when_steer_declines(monkeypatch) -> None:
    """If steer() declines (no agent turn actually active), the follow-up is
    queued as an ordinary next turn — never dropped."""
    bus = InProcBus()
    monkeypatch.setattr(bridge_mod, "_steer_active_turn", lambda text: False)
    replies: "queue.Queue[str]" = queue.Queue()
    bus.subscribe(ChatReply.topic, lambda m: replies.put(m.text))
    started: "queue.Queue[str]" = queue.Queue()
    release = threading.Event()

    def slow(c, t, session_key=None):
        started.put(t)
        release.wait(1.0)
        return {"text": f"done: {t}"}

    b = _bridge(bus, run_turn=slow)
    try:
        bus.publish(ChatMessage(text="first"))
        started.get(timeout=2.0)
        bus.publish(ChatMessage(text="second"))   # steer declines → queued
        release.set()
        seen: list[str] = []
        deadline = time.time() + 3.0
        while time.time() < deadline and len(seen) < 2:
            try:
                seen.append(replies.get(timeout=0.2))
            except queue.Empty:
                pass
        assert "done: first" in seen and "done: second" in seen
    finally:
        release.set()
        _stop(b, bus)
    assert b.turns == 2
