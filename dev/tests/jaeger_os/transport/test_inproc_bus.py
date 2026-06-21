"""Tests for ``jaeger_os.transport.inproc_bus`` — Track A.3.

Pins the publish/subscribe semantics + the request/ack tool-RPC
primitive that the brain's tools will call into at Track A.5+.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from jaeger_os import topics
from jaeger_os.transport import InProcBus, InProcBusOverflowError


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


# ── publish + subscribe ───────────────────────────────────────────

def test_single_subscriber_receives_message(bus):
    """Most basic case: one publisher, one subscriber, one message."""
    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def cb(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, cb)
    bus.publish(topics.Transcript(text="hello"))

    assert event.wait(timeout=1.0), "subscriber didn't receive the message"
    assert len(received) == 1
    assert received[0].text == "hello"


def test_multiple_subscribers_all_receive_message(bus):
    """Every subscriber on a topic gets a copy."""
    counts = [0, 0, 0]
    events = [threading.Event() for _ in range(3)]

    def make_cb(i):
        def cb(msg):
            counts[i] += 1
            events[i].set()
        return cb

    for i in range(3):
        bus.subscribe(topics.SENSE_TRANSCRIPT, make_cb(i))

    bus.publish(topics.Transcript(text="fanout"))

    for ev in events:
        assert ev.wait(timeout=1.0), "not every subscriber fired"
    assert counts == [1, 1, 1]


def test_no_subscriber_doesnt_block_publisher(bus):
    """Publishing to a topic with no subscribers is a no-op."""
    # Should return immediately without raising.
    bus.publish(topics.MotionCommand(linear_x_mps=0.5))
    # Nothing to assert — the test passes if publish returned.


def test_publish_overflow_raises_immediately():
    """A full delivery queue must not block the publisher."""
    bus = InProcBus(maxsize=1)
    try:
        bus._q.put_nowait(topics.Transcript(text="fills queue"))
        started = time.perf_counter()
        with pytest.raises(InProcBusOverflowError):
            bus.publish(topics.Transcript(text="overflow"))
        assert time.perf_counter() - started < 0.05
    finally:
        bus.close()


def test_subscribers_only_get_their_topic(bus):
    """Subscribing to /sense/transcript shouldn't receive /act/speech."""
    transcripts: list[topics.TopicMessage] = []
    speeches: list[topics.TopicMessage] = []
    transcripts_event = threading.Event()
    speeches_event = threading.Event()

    def transcript_cb(msg):
        transcripts.append(msg)
        transcripts_event.set()

    def speech_cb(msg):
        speeches.append(msg)
        speeches_event.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, transcript_cb)
    bus.subscribe(topics.ACT_SPEECH, speech_cb)
    bus.publish(topics.Transcript(text="for transcript"))
    bus.publish(topics.SpeechCommand(text="for speech"))

    assert transcripts_event.wait(timeout=1.0)
    assert speeches_event.wait(timeout=1.0)
    assert len(transcripts) == 1
    assert len(speeches) == 1
    assert transcripts[0].text == "for transcript"
    assert speeches[0].text == "for speech"


# ── unsubscribe ───────────────────────────────────────────────────

def test_unsubscribed_callback_stops_receiving(bus):
    """After unsubscribe, the callback shouldn't fire on future
    publishes."""
    received_after_unsubscribe = []
    received_before = threading.Event()

    def cb(msg):
        if received_before.is_set():
            received_after_unsubscribe.append(msg)
        else:
            received_before.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, cb)
    bus.publish(topics.Transcript(text="first"))
    assert received_before.wait(timeout=1.0)
    bus.unsubscribe(topics.SENSE_TRANSCRIPT, cb)
    bus.publish(topics.Transcript(text="second"))
    # Give the delivery thread a chance to dispatch (or not).
    time.sleep(0.1)
    assert received_after_unsubscribe == []


def test_unsubscribe_unknown_callback_is_noop(bus):
    """Unsubscribing a callback that was never subscribed shouldn't raise."""
    bus.unsubscribe(topics.SENSE_TRANSCRIPT, lambda m: None)


# ── request / ack (tool-RPC primitive) ────────────────────────────

def test_request_returns_matching_ack(bus):
    """request() blocks until an ack arrives with the matching cid."""
    cid = uuid.uuid4().hex

    def fake_tts(msg):
        # Acknowledge with the same correlation_id.
        bus.publish(topics.SpokenAck(
            ok=True,
            duration_s=0.5,
            correlation_id=msg.correlation_id,
        ))

    bus.subscribe(topics.ACT_SPEECH, fake_tts)
    ack = bus.request(
        topics.SpeechCommand(text="hi", correlation_id=cid),
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=1.0,
    )
    assert ack is not None
    assert isinstance(ack, topics.SpokenAck)
    assert ack.ok is True
    assert ack.correlation_id == cid


def test_request_times_out_on_no_ack(bus):
    """If nobody acks within ``timeout_s``, request() returns None."""
    cid = uuid.uuid4().hex
    ack = bus.request(
        topics.SpeechCommand(text="will fail", correlation_id=cid),
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=0.2,
    )
    assert ack is None


def test_request_ignores_wrong_correlation_id(bus):
    """An ack with a different correlation_id doesn't satisfy the wait."""
    cid_mine = uuid.uuid4().hex
    cid_other = uuid.uuid4().hex

    def stray_acker(msg):
        # Always ack with the WRONG cid.
        bus.publish(topics.SpokenAck(
            ok=True,
            correlation_id=cid_other,
        ))

    bus.subscribe(topics.ACT_SPEECH, stray_acker)
    ack = bus.request(
        topics.SpeechCommand(text="mine", correlation_id=cid_mine),
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=0.3,
    )
    assert ack is None  # timed out — wrong cid never satisfied us


def test_request_cleanup_unsubscribes_ack_callback(bus):
    """After request() returns, its ack-listener subscription must
    be gone — otherwise per-request subs accumulate forever."""
    cid = uuid.uuid4().hex

    def fake_tts(msg):
        bus.publish(topics.SpokenAck(
            ok=True, correlation_id=msg.correlation_id,
        ))

    bus.subscribe(topics.ACT_SPEECH, fake_tts)
    bus.request(
        topics.SpeechCommand(text="hi", correlation_id=cid),
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=1.0,
    )
    # The bus's _subscribers dict for SENSE_SPOKEN should be empty
    # (or list of length 0) — we never installed a permanent ack
    # subscriber, only the request-local one.
    with bus._subs_lock:
        assert bus._subscribers.get(topics.SENSE_SPOKEN, []) == [], (
            "request() leaked its per-call ack subscription"
        )


# ── exception isolation ──────────────────────────────────────────

def test_buggy_subscriber_doesnt_kill_bus(bus, capsys):
    """A callback that raises should not prevent other subscribers
    from receiving the same or future messages."""
    fired = threading.Event()

    def bad(msg):
        raise RuntimeError("kaboom")

    def good(msg):
        fired.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, bad)
    bus.subscribe(topics.SENSE_TRANSCRIPT, good)
    bus.publish(topics.Transcript(text="ping"))

    assert fired.wait(timeout=1.0), "good subscriber didn't fire"
    # And a second publish still works.
    fired.clear()
    bus.publish(topics.Transcript(text="ping2"))
    assert fired.wait(timeout=1.0), "good subscriber stopped after bad raised"

    # Optional: confirm the exception got logged to stderr.
    err = capsys.readouterr().err
    assert "kaboom" in err


# ── lifecycle ─────────────────────────────────────────────────────

def test_close_is_idempotent():
    """Calling close() twice doesn't raise."""
    bus = InProcBus()
    bus.close()
    bus.close()


def test_publish_after_close_is_silent_noop():
    """Publishing to a closed bus should not raise (closing happens
    during shutdown; we don't want a flurry of errors then)."""
    bus = InProcBus()
    bus.close()
    bus.publish(topics.Transcript(text="post-close"))  # no raise


def test_close_stops_delivery_thread():
    """After close(), the background delivery thread should exit."""
    bus = InProcBus()
    thread = bus._delivery_thread
    bus.close()
    # The join with timeout=2.0 inside close() should have done the work.
    assert not thread.is_alive(), "delivery thread still alive after close"
