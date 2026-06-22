"""Tests for ``jaeger_os.transport.broker`` — Track A.7.

Verifies the XPUB↔XSUB proxy actually bridges between two
otherwise-independent ZMQBus instances (simulates the
publisher-in-one-process / subscriber-in-another scenario).
Uses ``inproc://`` ZMQ endpoints so the tests don't depend on the
filesystem or network ports.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from jaeger_os.transport import topics
from jaeger_os.transport import Broker
from jaeger_os.transport.broker import _BrokerZMQBus


@pytest.fixture
def endpoints():
    """A fresh pair of inproc:// endpoints per test."""
    suffix = uuid.uuid4().hex[:8]
    return (
        f"inproc://jros-xsub-{suffix}",
        f"inproc://jros-xpub-{suffix}",
    )


def test_broker_starts_and_stops_cleanly(endpoints):
    xsub, xpub = endpoints
    broker = Broker(xsub_endpoint=xsub, xpub_endpoint=xpub)
    broker.start()
    assert broker._started is True
    assert broker._xsub is not None
    assert broker._xpub is not None
    broker.stop()
    assert broker._started is False


def test_broker_double_start_is_idempotent(endpoints):
    xsub, xpub = endpoints
    broker = Broker(xsub_endpoint=xsub, xpub_endpoint=xpub)
    broker.start()
    broker.start()  # no raise
    broker.stop()


def test_broker_double_stop_is_idempotent(endpoints):
    xsub, xpub = endpoints
    broker = Broker(xsub_endpoint=xsub, xpub_endpoint=xpub)
    broker.start()
    broker.stop()
    broker.stop()  # no raise


def test_broker_context_manager(endpoints):
    xsub, xpub = endpoints
    with Broker(xsub_endpoint=xsub, xpub_endpoint=xpub) as broker:
        assert broker._started is True
    assert broker._started is False


# ── the real test: two buses bridge through the broker ──────────

def test_pub_in_one_bus_reaches_sub_in_another(endpoints):
    """The actual cross-process scenario: a publisher Bus and a
    subscriber Bus share NO direct endpoint — they only connect to
    the broker's XSUB / XPUB endpoints.  The broker forwards.

    inproc:// + shared context simulates the cross-process case for
    the test; in production each process has its own context and
    the broker's ipc:// or tcp:// endpoints provide the bridge."""
    import zmq
    ctx = zmq.Context()
    xsub, xpub = endpoints

    # Use a shared context for inproc:// to work; production
    # multi-process uses ipc:// or tcp:// and doesn't share contexts.
    broker = Broker(xsub_endpoint=xsub, xpub_endpoint=xpub, ctx=ctx)
    broker.start()

    publisher = _BrokerZMQBus(
        pub_endpoint=xsub, sub_endpoint=xpub, ctx=ctx,
    )
    subscriber = _BrokerZMQBus(
        pub_endpoint=xsub, sub_endpoint=xpub, ctx=ctx,
    )

    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def on_transcript(msg):
        received.append(msg)
        event.set()

    subscriber.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
    # ZMQ late-joiner: let the subscription propagate through
    # the broker before publishing.
    time.sleep(0.3)
    publisher.publish(topics.Transcript(text="hello through broker"))

    try:
        assert event.wait(timeout=3.0), (
            "subscriber didn't receive bridged message"
        )
        assert received[0].text == "hello through broker"
    finally:
        publisher.close()
        subscriber.close()
        broker.stop()
        try:
            ctx.term()
        except Exception:
            pass


def test_pub_only_pubs_dont_drop_when_no_subscriber_yet(endpoints):
    """A publish to the broker with no subscriber attached doesn't
    block the publisher — the broker's XPUB side queues silently.
    Verify publisher.publish returns promptly."""
    import zmq
    ctx = zmq.Context()
    xsub, xpub = endpoints
    broker = Broker(xsub_endpoint=xsub, xpub_endpoint=xpub, ctx=ctx)
    broker.start()
    publisher = _BrokerZMQBus(
        pub_endpoint=xsub, sub_endpoint=xpub, ctx=ctx,
    )
    try:
        t0 = time.perf_counter()
        publisher.publish(topics.Transcript(text="alone"))
        elapsed = time.perf_counter() - t0
        # Publish should be fire-and-forget — never close to 1 s.
        assert elapsed < 0.5, f"publish blocked for {elapsed:.2f}s"
    finally:
        publisher.close()
        broker.stop()
        try:
            ctx.term()
        except Exception:
            pass
