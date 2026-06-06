"""bus.py — abstract Bus interface that both transports implement.

Two transport-backed implementations exist (see :mod:`inproc_bus`
and the future :mod:`zmq_bus`); a Node never references one
directly — it takes a ``Bus`` and the system wires the right one.

The interface is intentionally small.  Three operations:

  * :meth:`publish` — fire-and-forget; never blocks the publisher
    longer than the wire write.
  * :meth:`subscribe` — register a callback for a topic.  The
    callback runs on the Bus's delivery thread; subscribers that
    want to do work without blocking the delivery loop hand off
    to their own queue.
  * :meth:`request` — publish-and-wait-for-ack, keyed by
    ``correlation_id``.  This is the contract behind the operator's
    "tools = networking, nodes = execution" framing: a tool
    publishes a request topic (e.g. ``/act/speech``) and waits
    for the matching ack topic (``/sense/spoken``).
"""

from __future__ import annotations

import abc
from typing import Callable

from jaeger_os import topics


# A callback registered for a topic gets the decoded TopicMessage.
SubscriberFn = Callable[[topics.TopicMessage], None]


class Bus(abc.ABC):
    """Abstract Bus interface.  See subclasses for transport-specific
    behaviour."""

    @abc.abstractmethod
    def publish(self, msg: topics.TopicMessage) -> None:
        """Send ``msg`` to every subscriber of ``msg.topic``.
        Fire-and-forget; never blocks the publisher beyond the
        underlying transport's write."""

    @abc.abstractmethod
    def subscribe(self, topic: str, callback: SubscriberFn) -> None:
        """Register ``callback`` to fire on every message published
        to ``topic``.  Multiple subscribers on the same topic each
        get a copy."""

    @abc.abstractmethod
    def unsubscribe(self, topic: str, callback: SubscriberFn) -> None:
        """Drop a previously-registered subscriber.  No-op if the
        callback wasn't registered for that topic."""

    @abc.abstractmethod
    def request(
        self,
        request_msg: topics.TopicMessage,
        ack_topic: str,
        timeout_s: float = 10.0,
    ) -> topics.TopicMessage | None:
        """The tool-RPC primitive.  Publishes ``request_msg`` with
        its current ``correlation_id`` (call site fills it in),
        then blocks until an ``ack_topic`` message arrives with the
        matching ``correlation_id``.  Returns ``None`` on timeout.

        Subscribes to ``ack_topic`` for the duration of the request
        and unsubscribes on exit (so per-request subscriptions don't
        accumulate)."""

    @abc.abstractmethod
    def close(self) -> None:
        """Tear down the Bus.  Stops the delivery thread, drops
        subscribers, closes the transport.  Idempotent."""
