"""Tests for ``jaeger_os.transport.inproc_bus`` — Track A.3.

Pins the publish/subscribe semantics + the request/ack tool-RPC
primitive that the brain's tools will call into at Track A.5+.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from jaeger_os.transport import topics
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

    bus.subscribe(topics.SENSE_STT_TRANSCRIPT, cb)
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
        bus.subscribe(topics.SENSE_STT_TRANSCRIPT, make_cb(i))

    bus.publish(topics.Transcript(text="fanout"))

    for ev in events:
        assert ev.wait(timeout=1.0), "not every subscriber fired"
    assert counts == [1, 1, 1]


def test_no_subscriber_doesnt_block_publisher(bus):
    """Publishing to a topic with no subscribers is a no-op."""
    # Should return immediately without raising.
    bus.publish(topics.MotionCommand(linear_x_mps=0.5))
    # Nothing to assert — the test passes if publish returned.


def test_overflow_drops_the_oldest_and_never_blocks_the_publisher():
    """A subscriber that cannot keep up loses its OLDEST messages and
    nothing else changes.

    This replaces the old contract, where a full shared queue raised
    InProcBusOverflowError at the publisher. Raising (or blocking) makes
    one slow subscriber everyone else's problem, which is exactly the
    coupling per-subscriber queues exist to remove. For a frame or a
    telemetry tick the newest value is the useful one, so the oldest is
    what goes.
    """
    seen = []
    gate = threading.Event()

    def wedged(msg):
        gate.wait(timeout=5.0)      # hold the worker
        seen.append(msg)

    bus = InProcBus(maxsize=2)
    try:
        bus.subscribe(topics.SENSE_STT_TRANSCRIPT, wedged)
        time.sleep(0.1)
        started = time.perf_counter()
        for i in range(50):
            bus.publish(topics.Transcript(text=f"m{i}"))
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5, f"publishing blocked for {elapsed:.2f}s"
        stats = bus.stats()[topics.SENSE_STT_TRANSCRIPT]
        assert stats["dropped"] > 0, "overflow was not counted"
    finally:
        gate.set()
        bus.close()


def test_a_slow_subscriber_does_not_delay_another_topic():
    """The measurement that motivated per-subscriber queues: a 50 ms
    handler on one topic used to delay an unrelated message on another
    by 534 ms."""
    fast, slow = [], []
    bus = InProcBus()
    try:
        bus.subscribe(topics.ACT_DISPLAY_STATE,
                      lambda m: (time.sleep(0.05), slow.append(1)))
        bus.subscribe(topics.ACT_SPEECH_SPOKEN,
                      lambda m: fast.append(time.perf_counter()))
        time.sleep(0.1)
        started = time.perf_counter()
        for _ in range(10):
            bus.publish(topics.DisplayState(
                state="playing", progress=0.0, elapsed_ms=0))
        bus.publish(topics.SpokenAck())
        deadline = time.perf_counter() + 5.0
        while not fast and time.perf_counter() < deadline:
            time.sleep(0.002)
        assert fast, "the fast subscriber never ran"
        delay = fast[0] - started
        assert delay < 0.25, f"unrelated topic delayed {delay*1000:.0f} ms"
    finally:
        bus.close()


def test_a_slow_subscriber_still_gets_all_its_own_messages():
    """Isolation must not mean starvation: it only slows ITSELF."""
    got = []
    bus = InProcBus()
    try:
        bus.subscribe(topics.SENSE_STT_TRANSCRIPT,
                      lambda m: (time.sleep(0.01), got.append(m)))
        time.sleep(0.1)
        for i in range(10):
            bus.publish(topics.Transcript(text=f"m{i}"))
        deadline = time.perf_counter() + 5.0
        while len(got) < 10 and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert len(got) == 10
    finally:
        bus.close()


def test_ordering_is_preserved_per_subscriber():
    """Global ordering is given up; per-subscriber ordering is not."""
    got = []
    bus = InProcBus()
    try:
        bus.subscribe(topics.SENSE_STT_TRANSCRIPT, lambda m: got.append(m.text))
        time.sleep(0.1)
        for i in range(20):
            bus.publish(topics.Transcript(text=str(i)))
        deadline = time.perf_counter() + 5.0
        while len(got) < 20 and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert got == [str(i) for i in range(20)]
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

    bus.subscribe(topics.SENSE_STT_TRANSCRIPT, transcript_cb)
    bus.subscribe(topics.ACT_SPEECH_SAY, speech_cb)
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

    bus.subscribe(topics.SENSE_STT_TRANSCRIPT, cb)
    bus.publish(topics.Transcript(text="first"))
    assert received_before.wait(timeout=1.0)
    bus.unsubscribe(topics.SENSE_STT_TRANSCRIPT, cb)
    bus.publish(topics.Transcript(text="second"))
    # Give the delivery thread a chance to dispatch (or not).
    time.sleep(0.1)
    assert received_after_unsubscribe == []


def test_unsubscribe_unknown_callback_is_noop(bus):
    """Unsubscribing a callback that was never subscribed shouldn't raise."""
    bus.unsubscribe(topics.SENSE_STT_TRANSCRIPT, lambda m: None)


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

    bus.subscribe(topics.ACT_SPEECH_SAY, fake_tts)
    ack = bus.request(
        topics.SpeechCommand(text="hi", correlation_id=cid),
        ack_topic=topics.ACT_SPEECH_SPOKEN,
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
        ack_topic=topics.ACT_SPEECH_SPOKEN,
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

    bus.subscribe(topics.ACT_SPEECH_SAY, stray_acker)
    ack = bus.request(
        topics.SpeechCommand(text="mine", correlation_id=cid_mine),
        ack_topic=topics.ACT_SPEECH_SPOKEN,
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

    bus.subscribe(topics.ACT_SPEECH_SAY, fake_tts)
    bus.request(
        topics.SpeechCommand(text="hi", correlation_id=cid),
        ack_topic=topics.ACT_SPEECH_SPOKEN,
        timeout_s=1.0,
    )
    # The bus's _subscribers dict for ACT_SPEECH_SPOKEN should be empty
    # (or list of length 0) — we never installed a permanent ack
    # subscriber, only the request-local one.
    with bus._subs_lock:
        assert bus._subscribers.get(topics.ACT_SPEECH_SPOKEN, []) == [], (
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

    bus.subscribe(topics.SENSE_STT_TRANSCRIPT, bad)
    bus.subscribe(topics.SENSE_STT_TRANSCRIPT, good)
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


def test_close_stops_every_subscriber_worker():
    """There is no single delivery thread any more — each subscriber
    has its own, and close() must stop all of them."""
    bus = InProcBus()
    bus.subscribe(topics.SENSE_STT_TRANSCRIPT, lambda m: None)
    bus.subscribe(topics.ACT_SPEECH_SPOKEN, lambda m: None)
    threads = [s._thread for subs in bus._subscribers.values() for s in subs]
    assert len(threads) == 2
    bus.close()
    for thread in threads:
        assert not thread.is_alive(), "a subscriber worker outlived close()"


def test_unsubscribe_stops_that_subscribers_worker():
    bus = InProcBus()
    cb = lambda m: None          # noqa: E731
    try:
        bus.subscribe(topics.SENSE_STT_TRANSCRIPT, cb)
        thread = bus._subscribers[topics.SENSE_STT_TRANSCRIPT][0]._thread
        bus.unsubscribe(topics.SENSE_STT_TRANSCRIPT, cb)
        assert not thread.is_alive(), "worker outlived its subscription"
    finally:
        bus.close()
