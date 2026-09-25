"""inproc_bus.py — in-process Bus implementation.

The 30-line ``queue.Queue`` pattern from VoiceLLM
(``dev/docs/library_review/voicellm.md``), extended with:

  * Topic-typed messages (msgspec.Struct from ``jaeger_os.transport.topics``)
  * Per-topic subscriber lists (multiple callbacks per topic)
  * A delivery thread that drains the queue and fans out to
    subscribers (so a slow subscriber doesn't block the publisher)
  * The :meth:`request` tool-RPC primitive

Used when ``./launch`` runs in monolithic mode (the default —
all nodes in one Python process).  Latency is sub-microsecond per
publish; throughput is bounded by the Python GIL + delivery thread.
"""

from __future__ import annotations

import queue
import sys
import threading

from jaeger_os.contract.paths import SEP
from jaeger_os.contract.qos import RELIABLE, qos_for
from jaeger_os.transport import topics
from jaeger_os.transport.bus import Bus, SubscriberFn


class InProcBusOverflowError(RuntimeError):
    """No longer raised. Kept only so an ``except`` clause naming it
    still imports.

    The single-queue bus raised this at the PUBLISHER when the shared
    delivery queue filled. Per-subscriber queues made that the wrong
    shape: overflow is now one subscriber falling behind, and it drops
    its oldest message and counts it in ``InProcBus.stats()``. Raising
    would make one slow subscriber everyone else's problem.
    """
    """Raised when the in-process delivery queue is full.

    This preserves the Bus contract that ``publish()`` must not block:
    overflow is surfaced synchronously instead of hanging the publisher.
    """


class InProcBus(Bus):
    """In-process Bus backed by a single ``queue.Queue``.

    Threading model
    ---------------
    * **One queue and one worker thread PER SUBSCRIBER.** A slow
      callback starves only itself. Before this the bus had a single
      shared delivery thread, and a 50 ms handler on one topic delayed
      an unrelated message on another by 534 ms — measured. In a robot
      that means one slow renderer delaying e-stop delivery.
    * :meth:`publish` fans the message into each subscriber's queue and
      returns. It never runs a callback, so publishing cost does not
      depend on how slow any subscriber is.
    * **Ordering** is per-subscriber, not global. Each subscriber sees
      its own messages in publish order; two different subscribers may
      observe interleavings differently. This is what ROS/DDS gives and
      is the necessary price of not letting them block each other.
    * **Overflow drops the OLDEST** message for that subscriber and
      counts it (:meth:`stats`). Blocking the publisher would reinstate
      exactly the coupling this design removes, and for frames or
      telemetry a stale message is worth less than the newest one.
    * :meth:`subscribe` / :meth:`unsubscribe` are thread-safe via a
      coarse-grained lock — setup/teardown, not hot path.
    """

    def __init__(self, maxsize: int | None = None) -> None:
        # Per-subscriber depth OVERRIDE. None (the default) means each
        # subscription is sized by its topic's declared QoS, which is
        # where the policy belongs — a video frame and an e-stop should
        # not share a depth. Passing a number forces every subscription
        # to it, which tests use to provoke overflow deterministically.
        self._depth_override = max(1, int(maxsize)) if maxsize else None
        self._subs_lock = threading.Lock()
        self._subscribers: dict[str, list["_Subscription"]] = {}
        # Prefix subscriptions kept separate so the exact-match path
        # stays a single dict lookup.
        self._prefix_subs: dict[str, list["_Subscription"]] = {}
        self._closed = False

    # ── publish / subscribe ──────────────────────────────────────

    def publish(self, msg: topics.TopicMessage) -> None:
        """Hand ``msg`` to every matching subscriber's queue and return.

        Matching is PREFIX-based, mirroring ZMQ SUB semantics exactly, so
        a hierarchy behaves the same on both transports:

            /sense/                    every input
            /sense/camera/             every camera
            /sense/camera/cam0/        one camera

        Behaviour diverging between ``inproc`` and ``zmq`` would be a
        trap — code that worked fused would break the moment a node was
        moved to its own process.

        Never runs a callback, so publish latency is independent of how
        slow any subscriber is. Drops on a closed bus (shutdown is not
        the time for a flurry of errors).
        """
        if self._closed:
            return
        topic = msg.topic
        with self._subs_lock:
            # Exact subscribers are the overwhelmingly common case and
            # cost one dict hit. Prefix subscriptions are scanned only
            # if any exist at all, so a system that never uses the
            # hierarchy pays nothing for it.
            subs = list(self._subscribers.get(topic, ()))
            if self._prefix_subs:
                for prefix, plist in self._prefix_subs.items():
                    if topic.startswith(prefix):
                        subs.extend(plist)
        for sub in subs:
            sub.offer(msg)

    def subscribe(self, topic: str, callback: SubscriberFn) -> None:
        """Subscribe to an exact topic, or to a PREFIX ending in "/".

        A trailing separator is what distinguishes the two, and it is
        required for prefixes: without it ``/sense/cam`` would match
        ``/sense/camera/...`` and silently deliver a stream nobody
        asked for.
        """
        policy = qos_for(topic)
        depth = self._depth_override or policy.depth
        sub = _Subscription(topic, callback, depth, policy.reliability)
        with self._subs_lock:
            if topic.endswith(SEP):
                self._prefix_subs.setdefault(topic, []).append(sub)
            else:
                self._subscribers.setdefault(topic, []).append(sub)
        sub.start()

    def unsubscribe(self, topic: str, callback: SubscriberFn) -> None:
        table = (self._prefix_subs if topic.endswith(SEP)
                 else self._subscribers)
        with self._subs_lock:
            subs = table.get(topic)
            if not subs:
                return
            match = next((s for s in subs if s.callback == callback), None)
            if match is None:
                return  # not registered — silent, per the Bus contract
            subs.remove(match)
        match.stop()

    def stats(self) -> dict[str, dict]:
        """Per-topic delivery counters.

        ``dropped`` rising is the signal that a subscriber cannot keep
        up — invisible otherwise, because dropping is silent by design.
        """
        with self._subs_lock:
            items = [(t, list(s)) for t, s in self._subscribers.items()]
            items += [(t, list(s)) for t, s in self._prefix_subs.items()]
        out: dict[str, dict[str, int]] = {}
        for topic, subs in items:
            out[topic] = {
                "subscribers": len(subs),
                "delivered": sum(s.delivered for s in subs),
                "dropped": sum(s.dropped for s in subs),
                "queued": sum(s.queue_depth for s in subs),
                "depth": max((s._q.maxsize for s in subs), default=0),
                "reliability": subs[0].reliability if subs else "",
            }
        return out

    # ── tool-RPC: request → ack ──────────────────────────────────

    def request(
        self,
        request_msg: topics.TopicMessage,
        ack_topic: str,
        timeout_s: float = 10.0,
    ) -> topics.TopicMessage | None:
        """Publish ``request_msg``, wait for an ack on ``ack_topic``
        carrying the matching ``correlation_id``.

        The caller sets ``request_msg.correlation_id`` — typically a
        uuid4 hex. Blank still works, but a concurrent unrelated ack
        could satisfy the wait, so don't.
        """
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
        """Stop every subscriber worker and drop them. Idempotent."""
        if self._closed:
            return
        self._closed = True
        with self._subs_lock:
            subs = [s for lst in self._subscribers.values() for s in lst]
            subs += [s for lst in self._prefix_subs.values() for s in lst]
            self._subscribers.clear()
            self._prefix_subs.clear()
        for sub in subs:
            sub.stop()




class _Subscription:
    """One subscriber: its own bounded queue and its own worker thread.

    This is the isolation unit. Everything about how a slow callback is
    contained lives here — the bus itself just fans messages in.
    """

    __slots__ = ("topic", "callback", "_q", "_thread", "_stop",
                 "delivered", "dropped", "reliability")

    def __init__(self, topic: str, callback: SubscriberFn,
                 depth: int, reliability: str = "best_effort") -> None:
        self.topic = topic
        self.callback = callback
        self.reliability = reliability
        self._q: "queue.Queue[topics.TopicMessage]" = queue.Queue(
            maxsize=depth)
        self._stop = threading.Event()
        self.delivered = 0
        self.dropped = 0
        self._thread = threading.Thread(
            target=self._run,
            name=f"bus-sub:{topic}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    @property
    def queue_depth(self) -> int:
        return self._q.qsize()

    def offer(self, msg: topics.TopicMessage) -> None:
        """Enqueue without ever blocking the publisher.

        On overflow, evict the OLDEST and keep the newest: for a frame
        or a telemetry tick the freshest value is the useful one, and
        blocking here would recreate exactly the cross-subscriber
        coupling this class exists to remove.
        """
        try:
            self._q.put_nowait(msg)
            return
        except queue.Full:
            pass
        if self.reliability == RELIABLE:
            # A dropped e-stop is a safety event, not a dropped update.
            # We still cannot block the publisher without recreating the
            # coupling per-subscriber queues exist to remove — so the
            # message is lost either way. What changes is that it is
            # IMPOSSIBLE TO MISS rather than a silent counter.
            self.dropped += 1
            print(f"[bus] RELIABLE topic {self.topic} overflowed a "
                  f"subscriber queue (depth {self._q.maxsize}); a message "
                  f"was LOST. The subscriber is not keeping up.",
                  file=sys.stderr, flush=True)
            return
        try:
            self._q.get_nowait()       # evict oldest
            self._q.put_nowait(msg)
        except (queue.Empty, queue.Full):
            pass                        # raced the worker; nothing to do
        self.dropped += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.callback(msg)
                self.delivered += 1
            except Exception as exc:  # noqa: BLE001
                # One buggy subscriber must not take down its own
                # worker, let alone anyone else's.
                print(f"[bus] subscriber error on {self.topic}: "
                      f"{type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)


__all__ = ["InProcBus", "InProcBusOverflowError"]
