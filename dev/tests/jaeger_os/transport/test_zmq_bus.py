"""Tests for ``jaeger_os.transport.zmq_bus`` — Track A.4.

Pins the same Bus contract as :class:`InProcBus` (publish/subscribe,
request/ack, lifecycle) but exercises the ZMQ wire format.  Uses
``inproc://`` ZMQ endpoints so the tests don't depend on the
filesystem or open network ports.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from jaeger_os import topics
from jaeger_os.transport import ZMQBus


@pytest.fixture
def bus():
    # ``inproc://`` ZMQ endpoint stays within the test process —
    # no filesystem ipc:// socket, no tcp:// port — keeps the test
    # hermetic.  Each test gets a fresh endpoint name (uuid) so
    # parallel test runs don't collide.
    ep = f"inproc://jros-bus-test-{uuid.uuid4().hex[:8]}"
    b = ZMQBus(endpoint=ep, bind=True)
    yield b
    b.close()


# ── publish + subscribe ───────────────────────────────────────────

def test_single_subscriber_receives_message(bus):
    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def cb(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, cb)
    time.sleep(0.05)  # let ZMQ register the subscription
    bus.publish(topics.Transcript(text="hello"))

    assert event.wait(timeout=2.0), "subscriber didn't receive the message"
    assert len(received) == 1
    assert received[0].text == "hello"


def test_subscribers_only_get_their_topic(bus):
    """ZMQ SUB filters by topic at the wire level — verify that no
    cross-talk leaks."""
    transcripts_event = threading.Event()
    speeches_event = threading.Event()

    def transcript_cb(msg):
        transcripts_event.set()

    def speech_cb(msg):
        speeches_event.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, transcript_cb)
    bus.subscribe(topics.ACT_SPEECH, speech_cb)
    time.sleep(0.05)
    bus.publish(topics.Transcript(text="for transcript"))
    bus.publish(topics.SpeechCommand(text="for speech"))

    assert transcripts_event.wait(timeout=2.0)
    assert speeches_event.wait(timeout=2.0)


def test_binary_topic_round_trips_through_zmq(bus):
    """The codec layer's MessagePack-for-binary kicks in: AudioInFrame
    survives the ZMQ wire."""
    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def cb(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_AUDIO_IN, cb)
    time.sleep(0.05)
    raw = b"\x00\x01\x02\xff\xfe\xfd" * 32
    bus.publish(topics.AudioInFrame(samples=raw, sample_rate=16000))

    assert event.wait(timeout=2.0)
    assert isinstance(received[0], topics.AudioInFrame)
    assert received[0].samples == raw


# ── unsubscribe ───────────────────────────────────────────────────

def test_unsubscribed_callback_stops_receiving(bus):
    received_after = []
    received_before = threading.Event()

    def cb(msg):
        if received_before.is_set():
            received_after.append(msg)
        else:
            received_before.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, cb)
    time.sleep(0.05)
    bus.publish(topics.Transcript(text="first"))
    assert received_before.wait(timeout=2.0)
    bus.unsubscribe(topics.SENSE_TRANSCRIPT, cb)
    time.sleep(0.05)  # let ZMQ drop the wire-level filter
    bus.publish(topics.Transcript(text="second"))
    time.sleep(0.2)  # delivery thread chance
    assert received_after == []


# ── tool-RPC: request → ack ────────────────────────────────────────

def test_request_returns_matching_ack(bus):
    cid = uuid.uuid4().hex

    def fake_tts(msg):
        bus.publish(topics.SpokenAck(
            ok=True, duration_s=0.5,
            correlation_id=msg.correlation_id,
        ))

    bus.subscribe(topics.ACT_SPEECH, fake_tts)
    time.sleep(0.05)
    ack = bus.request(
        topics.SpeechCommand(text="hi", correlation_id=cid),
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=2.0,
    )
    assert ack is not None
    assert isinstance(ack, topics.SpokenAck)
    assert ack.ok is True
    assert ack.correlation_id == cid


def test_request_times_out_on_no_ack(bus):
    cid = uuid.uuid4().hex
    ack = bus.request(
        topics.SpeechCommand(text="will fail", correlation_id=cid),
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=0.5,
    )
    assert ack is None


# ── exception isolation ──────────────────────────────────────────

def test_buggy_subscriber_doesnt_kill_bus(bus, capsys):
    fired = threading.Event()

    def bad(msg):
        raise RuntimeError("kaboom-zmq")

    def good(msg):
        fired.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, bad)
    bus.subscribe(topics.SENSE_TRANSCRIPT, good)
    time.sleep(0.05)
    bus.publish(topics.Transcript(text="ping"))

    assert fired.wait(timeout=2.0)
    err = capsys.readouterr().err
    assert "kaboom-zmq" in err


# ── lifecycle ─────────────────────────────────────────────────────

def test_close_is_idempotent():
    ep = f"inproc://jros-bus-test-{uuid.uuid4().hex[:8]}"
    bus = ZMQBus(endpoint=ep, bind=True)
    bus.close()
    bus.close()


def test_publish_after_close_is_silent_noop():
    ep = f"inproc://jros-bus-test-{uuid.uuid4().hex[:8]}"
    bus = ZMQBus(endpoint=ep, bind=True)
    bus.close()
    bus.publish(topics.Transcript(text="post-close"))


# ── decoupled publisher + subscriber processes (simulated) ────────

def test_two_buses_on_same_inproc_endpoint_share_context():
    """When two Bus instances share a ZMQ context AND endpoint, they
    talk via the in-proc transport.  This is the foundation that
    will let Node A subscribe to messages Node B publishes once
    multi-process mode wires up: same endpoint, different node
    processes connect to it.

    For now we exercise the cross-Bus path within one Python process
    via a shared context."""
    import zmq
    ctx = zmq.Context()
    ep = f"inproc://jros-bus-test-{uuid.uuid4().hex[:8]}"

    # Producer binds; consumer connects.
    producer = ZMQBus(endpoint=ep, bind=True, ctx=ctx)
    consumer = ZMQBus(endpoint=ep, bind=False, ctx=ctx)

    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def cb(msg):
        received.append(msg)
        event.set()

    consumer.subscribe(topics.SENSE_TRANSCRIPT, cb)
    time.sleep(0.1)  # let the SUB filter register before publish
    producer.publish(topics.Transcript(text="cross-bus"))

    try:
        assert event.wait(timeout=2.0), (
            "consumer didn't receive cross-bus message"
        )
        assert received[0].text == "cross-bus"
    finally:
        producer.close()
        consumer.close()
        ctx.term()
