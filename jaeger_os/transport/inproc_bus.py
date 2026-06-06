"""inproc_bus.py — in-process Bus implementation.

The 30-line ``queue.Queue`` pattern from VoiceLLM
(``dev_docs/library_review/voicellm.md``), extended with:

  * Topic-typed messages (msgspec.Struct from ``jaeger_os.topics``)
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
import threading
import time
from typing import Any

from jaeger_os import topics
from jaeger_os.transport.bus import Bus, SubscriberFn


class InProcBus(Bus):
    """In-process Bus backed by a single ``queue.Queue``.

    Threading model
    ---------------
    * One delivery thread drains the queue and fans out to
      subscribers.  Subscribers run on the delivery thread, so a
      blocking subscriber will back-pressure the entire Bus.
      Subscribers that need to do work should hand off to their
      own thread / queue.
    * :meth:`publish` is thread-safe and non-blocking up to the
      queue's ``maxsize`` (default 2048, matches VoiceLLM).
    * :meth:`subscribe` / :meth:`unsubscribe` are thread-safe via
      a coarse-grained lock — these are setup / teardown operations,
      not hot-path.
    """

    def __init__(self, maxsize: int = 2048) -> None:
        self._q: "queue.Queue[topics.TopicMessage | None]" = queue.Queue(
            maxsize=maxsize
        )
        # topic → list of callbacks.  Tuple of (str, list) so we can
        # swap the list atomically when adding/removing without
        # holding the lock through delivery.
        self._subs_lock = threading.Lock()
        self._subscribers: dict[str, list[SubscriberFn]] = {}
        # Lifecycle.
        self._closed = False
        self._delivery_thread = threading.Thread(
            target=self._delivery_loop,
            name="inproc-bus-delivery",
            daemon=True,
        )
        self._delivery_thread.start()

    # ── publish / subscribe ──────────────────────────────────────

    def publish(self, msg: topics.TopicMessage) -> None:
        """Enqueue ``msg`` for delivery to ``msg.topic`` subscribers.
        Drops the message on a closed Bus (silent — closing happens
        during shutdown and we don't want a flurry of errors then)."""
        if self._closed:
            return
        # ``put`` will raise queue.Full on overflow.  At our scale
        # 2048 messages of headroom is plenty; raising loudly
        # surfaces real publisher misbehaviour (a runaway loop) at
        # development time.
        self._q.put(msg)

    def subscribe(self, topic: str, callback: SubscriberFn) -> None:
        with self._subs_lock:
            self._subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: SubscriberFn) -> None:
        with self._subs_lock:
            subs = self._subscribers.get(topic)
            if not subs:
                return
            try:
                subs.remove(callback)
            except ValueError:
                return  # not registered — silent no-op per the Bus contract

    # ── tool-RPC: request → ack ──────────────────────────────────

    def request(
        self,
        request_msg: topics.TopicMessage,
        ack_topic: str,
        timeout_s: float = 10.0,
    ) -> topics.TopicMessage | None:
        """Publish ``request_msg``, subscribe to ``ack_topic``, wait
        for an ack carrying the matching ``correlation_id``.

        The caller is responsible for setting
        ``request_msg.correlation_id`` to something reasonably unique
        — typically a uuid4 hex.  If it's blank the wait still works
        but a concurrent unrelated ack could satisfy it (don't do this)."""
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
        """Stop the delivery thread + drop subscribers.  Idempotent."""
        if self._closed:
            return
        self._closed = True
        # Sentinel wakes the delivery thread out of queue.get().
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass  # delivery thread is alive — sentinel will be picked up next drain
        self._delivery_thread.join(timeout=2.0)
        with self._subs_lock:
            self._subscribers.clear()

    # ── delivery loop ────────────────────────────────────────────

    def _delivery_loop(self) -> None:
        """Drain the queue and fan out to subscribers.  Exceptions
        in subscriber callbacks are caught + printed (we don't want
        one buggy subscriber to wedge the whole bus)."""
        while True:
            try:
                msg = self._q.get(timeout=0.5)
            except queue.Empty:
                if self._closed:
                    return
                continue
            if msg is None:
                # Close sentinel.
                return
            # Snapshot the subscriber list outside the delivery
            # lock — subscribe/unsubscribe operates on a separate
            # list mutation under that lock, so a snapshot via copy
            # is consistent.
            with self._subs_lock:
                snapshot = list(self._subscribers.get(msg.topic, ()))
            for cb in snapshot:
                try:
                    cb(msg)
                except Exception as exc:  # noqa: BLE001
                    # Don't let a subscriber bug take down the bus.
                    # Print to stderr so it shows up in normal logs.
                    import sys
                    print(
                        f"[inproc-bus] subscriber exception on "
                        f"{msg.topic}: {type(exc).__name__}: {exc}",
                        file=sys.stderr, flush=True,
                    )
