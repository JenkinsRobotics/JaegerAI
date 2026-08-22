"""zmq_bus.py — ZMQ pub/sub Bus implementation.

Same :class:`~jaeger_os.transport.Bus` interface as
:class:`~jaeger_os.transport.InProcBus`; behind it lives a single
``zmq.PUB`` socket for outgoing messages + a ``zmq.SUB`` socket
listened on by a delivery thread.

Endpoint addressing
-------------------
* ``inproc://jros-bus``     same-process Bus.  Mostly used by tests
                            that want to exercise the ZMQ code path
                            without the OS hop; the default
                            production in-process transport is
                            :class:`InProcBus`, which is faster.
* ``ipc:///tmp/jros.bus``   same-machine, different-process.  The
                            default when ``./launch --multiprocess``
                            spawns nodes locally.
* ``tcp://<host>:<port>``   cross-machine (Mac↔Jetson↔Teensy when
                            JP01 wires up at Track C).

The PUB socket binds the endpoint and every node's SUB socket
connects to it.  Backpressure is governed by ZMQ's HWM (high-water
mark) — at our scale 1000 messages per topic is plenty; slow
subscribers drop messages rather than back-pressuring the
publisher.  (The InProcBus instead uses a 2048-deep queue.Queue
that DOES back-pressure — different defaults for different
transports.)

Topic framing
-------------
ZMQ multi-part frames are used so the topic name rides in frame 0
and the payload rides in frame 1.  This lets the SUB socket filter
by topic prefix at the wire level without decoding every
message — important when one node subscribes to a small subset of
a busy publisher's topics.

Wire format
-----------
:mod:`jaeger_os.transport.codec` picks the format per topic
(JSON for text topics, MessagePack for binary topics).  ZMQ sees
opaque ``bytes`` either way.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import zmq

from jaeger_os.transport import topics
from jaeger_os.transport.bus import Bus, SubscriberFn
from jaeger_os.transport.codec import decode, encode


DEFAULT_ENDPOINT = "ipc:///tmp/jros-bus.sock"


class ZMQBus(Bus):
    """ZMQ pub/sub Bus.

    The Bus owns:
      * one PUB socket that binds the endpoint (the "broker" role)
      * one SUB socket that connects to the same endpoint
        (subscriptions added per :meth:`subscribe` call)
      * a delivery thread that reads SUB-side messages and fans out
        to Python subscribers, mirroring InProcBus's behaviour

    There's exactly one publisher per endpoint by design — for
    cross-process / cross-machine, every node connects to a single
    PUB endpoint that one process binds.  At Track A.6 ``./launch``
    will arrange this; for now the test fixture binds it itself.

    Threading model is identical to InProcBus's: one delivery thread
    drains the SUB socket and runs subscriber callbacks.  Exceptions
    in callbacks are caught + printed.

    Note: ``request()`` semantics are identical to InProcBus — bind
    a per-call ack subscriber, publish, wait, unbind.  The latency
    cost is one ZMQ round-trip (~10-50µs locally).
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        bind: bool = True,
        ctx: zmq.Context | None = None,
        hwm: int = 1000,
        recv_timeout_ms: int = 200,
    ) -> None:
        self._endpoint = endpoint
        self._ctx_owned = ctx is None
        self._ctx = ctx or zmq.Context.instance()
        self._hwm = hwm
        self._recv_timeout_ms = recv_timeout_ms

        # PUB side — bind if we're the broker, connect otherwise.
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.setsockopt(zmq.SNDHWM, hwm)
        if bind:
            self._pub.bind(endpoint)
        else:
            self._pub.connect(endpoint)

        # SUB side — always connects (consumer).  Topic subscriptions
        # are added per :meth:`subscribe` call.
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.RCVHWM, hwm)
        self._sub.setsockopt(zmq.RCVTIMEO, recv_timeout_ms)
        self._sub.connect(endpoint)

        # Per-topic Python subscriber lists.
        self._subs_lock = threading.Lock()
        self._subscribers: dict[str, list[SubscriberFn]] = {}

        self._closed = False
        # Brief sleep so the PUB→SUB connection settles before the
        # first publish — ZMQ's late-joiner pattern drops messages
        # to subscribers who haven't fully connected yet.  This is
        # a known characteristic; tests + production both pause.
        time.sleep(0.05)
        self._delivery_thread = threading.Thread(
            target=self._delivery_loop,
            name="zmq-bus-delivery",
            daemon=True,
        )
        self._delivery_thread.start()

    # ── publish / subscribe ──────────────────────────────────────

    def publish(self, msg: topics.TopicMessage) -> None:
        if self._closed:
            return
        wire = encode(msg)
        # Multi-part frame: [topic name bytes, payload bytes].  The
        # SUB filter operates on frame 0's prefix.
        self._pub.send_multipart([msg.topic.encode("utf-8"), wire])

    def subscribe(self, topic: str, callback: SubscriberFn) -> None:
        with self._subs_lock:
            existing = self._subscribers.get(topic, [])
            if not existing:
                # First Python subscriber for this topic — also
                # subscribe at the ZMQ wire level.
                self._sub.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))
            existing.append(callback)
            self._subscribers[topic] = existing

    def unsubscribe(self, topic: str, callback: SubscriberFn) -> None:
        with self._subs_lock:
            subs = self._subscribers.get(topic)
            if not subs:
                return
            try:
                subs.remove(callback)
            except ValueError:
                return
            if not subs:
                # Last subscriber for this topic — drop the ZMQ
                # wire-level subscription too.
                try:
                    self._sub.setsockopt(zmq.UNSUBSCRIBE, topic.encode("utf-8"))
                except zmq.ZMQError:
                    pass  # socket already closed

    # ── tool-RPC: request → ack ──────────────────────────────────

    def request(
        self,
        request_msg: topics.TopicMessage,
        ack_topic: str,
        timeout_s: float = 10.0,
    ) -> topics.TopicMessage | None:
        target_cid = request_msg.correlation_id
        ack_event = threading.Event()
        received: list[topics.TopicMessage] = []

        def _on_ack(msg: topics.TopicMessage) -> None:
            if msg.correlation_id == target_cid:
                received.append(msg)
                ack_event.set()

        self.subscribe(ack_topic, _on_ack)
        try:
            self.publish(request_msg)
            if not ack_event.wait(timeout=timeout_s):
                return None
            return received[0]
        finally:
            self.unsubscribe(ack_topic, _on_ack)

    # ── lifecycle ────────────────────────────────────────────────

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._delivery_thread.join(timeout=2.0)
        try:
            self._pub.close(linger=0)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._sub.close(linger=0)
        except Exception:  # noqa: BLE001
            pass
        if self._ctx_owned:
            try:
                self._ctx.term()
            except Exception:  # noqa: BLE001
                pass

    # ── delivery loop ────────────────────────────────────────────

    def _delivery_loop(self) -> None:
        while not self._closed:
            try:
                frames = self._sub.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError as exc:
                if self._closed or exc.errno == zmq.ETERM:
                    return
                import sys
                print(
                    f"[zmq-bus] recv error: {exc}",
                    file=sys.stderr, flush=True,
                )
                continue
            if len(frames) < 2:
                continue
            topic_bytes, payload = frames[0], frames[1]
            topic = topic_bytes.decode("utf-8", errors="replace")
            try:
                msg = decode(payload, topic)
            except Exception as exc:  # noqa: BLE001
                import sys
                print(
                    f"[zmq-bus] decode error on {topic!r}: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr, flush=True,
                )
                continue
            with self._subs_lock:
                snapshot = list(self._subscribers.get(topic, ()))
            for cb in snapshot:
                try:
                    cb(msg)
                except Exception as exc:  # noqa: BLE001
                    import sys
                    print(
                        f"[zmq-bus] subscriber exception on {topic!r}: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr, flush=True,
                    )
