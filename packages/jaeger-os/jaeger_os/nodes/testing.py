"""testing.py — isolate ONE node on a private bus and drive it.

A node is just a thing that subscribes to input topics and publishes
output topics (see :class:`Node`).  To evaluate one in isolation you
don't need the whole app — boot it alone on a fresh ``InProcBus``,
publish synthetic inputs, and capture what it emits.

Pairs with ``agent/trace.py``: a node's bus activity is observable while
you poke it.  This is how the imported-under-development media/animation
nodes get vetted before anything wires them into the live runtime.

    from jaeger_os.nodes.media.node import MediaNode
    from jaeger_os.transport import topics
    with NodeHarness(lambda bus: MediaNode(bus=bus,
                                           install_signal_handlers=False)) as h:
        states = h.capture(topics.SENSE_MEDIA_STATE)
        h.publish(topics.MediaCommand(path="clip.mp4"))
        h.wait(lambda: states)
        print(states[-1])

The factory MUST pass ``install_signal_handlers=False`` — the node runs
on a worker thread, and signal handlers can only be installed on the
main thread.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from jaeger_os.nodes.base import NodeState
from jaeger_os.transport.inproc_bus import InProcBus


class NodeHarness:
    """Boot one Node on a private InProcBus; publish inputs, capture outputs."""

    def __init__(self, factory: Callable[[Any], Any]) -> None:
        self.bus = InProcBus()
        self.node = factory(self.bus)
        self._thread: threading.Thread | None = None

    def start(self, timeout_s: float = 2.0) -> "NodeHarness":
        self._thread = threading.Thread(
            target=self.node.run, name=f"harness-{self.node.name}", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            st = self.node.state
            if st == NodeState.RUNNING:
                return self
            if st == NodeState.FAILED:
                raise RuntimeError(
                    f"node failed during setup: {self.node.health().get('error')}")
            time.sleep(0.01)
        raise TimeoutError(
            f"node {self.node.name} did not reach RUNNING in {timeout_s}s")

    def capture(self, topic: str) -> list[Any]:
        """Collect every message on ``topic`` into a live list (returned)."""
        msgs: list[Any] = []
        self.bus.subscribe(topic, msgs.append)
        return msgs

    def publish(self, msg: Any) -> None:
        self.bus.publish(msg)

    def wait(self, cond: Callable[[], bool], timeout_s: float = 2.0,
             poll_s: float = 0.01) -> bool:
        """Block until ``cond()`` is truthy or timeout; returns the final value."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if cond():
                return True
            time.sleep(poll_s)
        return bool(cond())

    def stop(self) -> None:
        try:
            self.node.stop()
            if self._thread is not None:
                self._thread.join(timeout=3.0)
        finally:
            self.bus.close()

    def __enter__(self) -> "NodeHarness":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()
