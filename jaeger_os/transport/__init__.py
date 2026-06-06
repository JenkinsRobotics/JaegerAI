"""jaeger_os.transport — node message transport for 0.4.

Two layers:

  * :mod:`jaeger_os.transport.codec` — wire-format encode/decode.
    JSON for text topics (debuggable in ``tcpdump`` / Wireshark);
    MessagePack for binary topics (audio frames, vision frames) —
    smaller on the wire and msgspec encodes ``bytes`` natively.
    Picks the right format from the topic name so callers don't
    have to remember.

  * :mod:`jaeger_os.transport.inproc_bus` — in-process Bus, the
    VoiceLLM ``queue.Queue`` pattern extended with topic-typing.
    The default transport when ``./launch`` runs in monolithic
    mode (all nodes in one Python process).

  * :mod:`jaeger_os.transport.zmq_bus` (Track A.4) — ZMQ pub/sub
    behind the same Bus interface, used in ``--multiprocess`` mode.

All three import from :mod:`jaeger_os.topics`; nothing in topics.py
imports from here.  Schemas are transport-free by construction.
"""

from .bus import Bus, SubscriberFn
from .codec import encode, decode, is_binary_topic
from .inproc_bus import InProcBus
from .zmq_bus import ZMQBus, DEFAULT_ENDPOINT as ZMQ_DEFAULT_ENDPOINT

__all__ = [
    "Bus", "SubscriberFn",
    "encode", "decode", "is_binary_topic",
    "InProcBus", "ZMQBus", "ZMQ_DEFAULT_ENDPOINT",
]
