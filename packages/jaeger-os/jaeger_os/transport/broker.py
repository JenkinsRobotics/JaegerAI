"""broker.py — ZMQ XPUB↔XSUB proxy.

Closes the cross-process gap the unit tests discovered at A.6:
``ZMQBus`` binds both PUB + SUB to the same endpoint, which works
in-process (shared ZMQ context internally routes between sockets)
but NOT across separate processes (each process has its own
context — no shared routing).

The fix is the canonical ZMQ pub/sub topology — one broker process
runs a :func:`zmq.proxy` between two well-known endpoints:

    publishers → CONNECT to XSUB endpoint  → broker forwards →
    subscribers ← CONNECT to XPUB endpoint ← broker forwards

Every node (whether brain, STT, TTS, vision, motor controller)
becomes a peer that just connects.  No node binds anything except
the broker itself.

Lifecycle
---------
``./launch --mode multiprocess`` spawns the broker as a background
thread before any node subprocess starts; the env var
``JAEGER_TRANSPORT_XSUB`` + ``JAEGER_TRANSPORT_XPUB`` carry the
endpoints so each spawned process can connect to them via
:class:`ZMQBus`.

In monolithic mode (``./launch``, default) the broker isn't
needed — ``InProcBus`` handles everything in-process.

API
---
* :class:`Broker` — start / stop a broker thread + context.
* :func:`make_bus_for_node` — builder helper: given the env-passed
  XSUB+XPUB endpoints, returns a :class:`ZMQBus` configured to
  CONNECT (not bind) to the broker.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

import zmq

from jaeger_os.transport.zmq_bus import ZMQBus


DEFAULT_XSUB_ENDPOINT = "ipc:///tmp/jros-xsub.sock"
DEFAULT_XPUB_ENDPOINT = "ipc:///tmp/jros-xpub.sock"


class Broker:
    """ZMQ XPUB↔XSUB proxy thread.

    Use it as a context manager OR call ``start()`` + ``stop()``
    explicitly.  Idempotent on both ends.
    """

    def __init__(
        self,
        *,
        xsub_endpoint: str = DEFAULT_XSUB_ENDPOINT,
        xpub_endpoint: str = DEFAULT_XPUB_ENDPOINT,
        ctx: zmq.Context | None = None,
    ) -> None:
        self.xsub_endpoint = xsub_endpoint
        self.xpub_endpoint = xpub_endpoint
        self._ctx_owned = ctx is None
        self._ctx = ctx or zmq.Context.instance()
        self._xsub: zmq.Socket | None = None
        self._xpub: zmq.Socket | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._started = False

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        if self._started:
            return
        # XSUB faces publishers: they CONNECT here to send to us.
        self._xsub = self._ctx.socket(zmq.XSUB)
        self._xsub.bind(self.xsub_endpoint)
        # XPUB faces subscribers: they CONNECT here to receive from us.
        self._xpub = self._ctx.socket(zmq.XPUB)
        self._xpub.bind(self.xpub_endpoint)
        self._thread = threading.Thread(
            target=self._proxy_loop,
            name="zmq-broker",
            daemon=True,
        )
        self._thread.start()
        # Brief settle so binds take effect before publishers connect.
        time.sleep(0.05)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._stopped.set()
        # Closing the sockets makes zmq.proxy return.
        for sock in (self._xsub, self._xpub):
            if sock is None:
                continue
            try:
                sock.close(linger=0)
            except Exception:  # noqa: BLE001
                pass
        self._xsub = None
        self._xpub = None
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._thread = None
        if self._ctx_owned:
            try:
                self._ctx.term()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "Broker":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    # ── proxy loop ────────────────────────────────────────────────

    def _proxy_loop(self) -> None:
        """Forward XSUB ← publishers → XPUB → subscribers.

        ``zmq.proxy`` blocks until one of the sockets closes
        (which our ``stop()`` triggers via ``close(linger=0)``).
        Any other ZMQ error here is recorded but not fatal —
        broker robustness is Track D supervisor work.
        """
        try:
            zmq.proxy(self._xsub, self._xpub)
        except zmq.ContextTerminated:
            return
        except zmq.ZMQError as exc:
            if self._stopped.is_set():
                return
            import sys
            print(
                f"[zmq-broker] proxy exited: {exc}",
                file=sys.stderr, flush=True,
            )


# ── ZMQBus builder for nodes living in subprocesses ──────────────

def make_bus_for_node(
    *,
    xsub_endpoint: str | None = None,
    xpub_endpoint: str | None = None,
    ctx: zmq.Context | None = None,
) -> ZMQBus:
    """Build a :class:`ZMQBus` that CONNECTS to the broker
    (does not bind any endpoint itself).

    Resolution order for endpoints:
        1. explicit kwargs (xsub_endpoint / xpub_endpoint)
        2. JAEGER_TRANSPORT_XSUB / JAEGER_TRANSPORT_XPUB env vars
        3. :data:`DEFAULT_XSUB_ENDPOINT` / :data:`DEFAULT_XPUB_ENDPOINT`

    The broker MUST already be running before this returns — the
    underlying ZMQBus does its 50 ms settle in __init__, and if
    the broker isn't bound the connect will silently no-op and
    the first publish will be dropped.
    """
    xsub = xsub_endpoint or os.environ.get(
        "JAEGER_TRANSPORT_XSUB", DEFAULT_XSUB_ENDPOINT,
    )
    xpub = xpub_endpoint or os.environ.get(
        "JAEGER_TRANSPORT_XPUB", DEFAULT_XPUB_ENDPOINT,
    )
    # ZMQBus's PUB connects to the XSUB endpoint (broker's
    # publisher-facing side); its SUB connects to XPUB (broker's
    # subscriber-facing side).  We accomplish that by passing
    # endpoint=xsub for the PUB side via bind=False — but ZMQBus
    # was designed to use ONE endpoint for both.  Subclass it
    # locally to split.
    return _BrokerZMQBus(
        pub_endpoint=xsub, sub_endpoint=xpub, ctx=ctx,
    )


class _BrokerZMQBus(ZMQBus):
    """ZMQBus variant that uses DIFFERENT endpoints for PUB and SUB
    so it can connect to an XPUB↔XSUB broker."""

    def __init__(
        self,
        *,
        pub_endpoint: str,
        sub_endpoint: str,
        ctx: zmq.Context | None = None,
        hwm: int = 1000,
        recv_timeout_ms: int = 200,
    ) -> None:
        # Bypass ZMQBus.__init__ since it forces a single endpoint;
        # reproduce its setup with two endpoints instead.
        from jaeger_os.transport.bus import Bus  # noqa: F401  (Bus parent)
        # NB: we duplicate the parent's init body rather than fight
        # super() — the broker shape is the exception, the inproc
        # ZMQBus is the rule.
        import threading as _threading
        self._endpoint = f"{pub_endpoint} ↔ {sub_endpoint}"
        self._ctx_owned = ctx is None
        self._ctx = ctx or zmq.Context.instance()
        self._hwm = hwm
        self._recv_timeout_ms = recv_timeout_ms

        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.setsockopt(zmq.SNDHWM, hwm)
        self._pub.connect(pub_endpoint)

        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.RCVHWM, hwm)
        self._sub.setsockopt(zmq.RCVTIMEO, recv_timeout_ms)
        self._sub.connect(sub_endpoint)

        self._subs_lock = _threading.Lock()
        self._subscribers = {}

        self._closed = False
        time.sleep(0.05)
        self._delivery_thread = _threading.Thread(
            target=self._delivery_loop,
            name="zmq-bus-delivery",
            daemon=True,
        )
        self._delivery_thread.start()
