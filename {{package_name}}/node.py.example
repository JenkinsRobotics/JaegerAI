"""node.py — the four-phase Node lifecycle skeleton.

A Node is a long-lived, bus-addressable unit of work with a four-phase
lifecycle (mirrors JaegerOS's ``jaeger_os/nodes/base.py`` Node ABC):

  setup     called once when the supervisor starts the node. Subscribe to
            topics, open resources, build the underlying engine.
  tick      called repeatedly while running. Do real work here. The
            default sleeps briefly if a node only reacts to subscriber
            callbacks and has nothing to poll.
  teardown  called once when the supervisor stops the node. Unsubscribe,
            flush, close resources.
  health    queryable at any time. Return a dict the supervisor treats as
            opaque and may forward to an operator-facing health surface.

Threading rule: the bus delivery thread MUST NOT block on slow work, or
it back-pressures every other subscriber on every other topic. Slow work
(model inference, I/O, hardware calls) belongs in tick() via an internal
queue, not in a subscriber callback — see kokoro_tts's TTSNode in
JaegerOS for the reference implementation of this pattern.

Copy to node.py (drop the .example suffix), rename {{PackageName}}Node and
make_{{package_name}}_node to match your module, and wire it to whatever
engine/adapter this module actually drives.
"""

from __future__ import annotations

import queue
from typing import Any, Protocol

# Uncomment once this module has a real JaegerOS dependency pinned:
# from jaeger_os.nodes.base import Node
# from jaeger_os.transport import Bus, topics


class Engine(Protocol):
    """The bit of the underlying engine/adapter this node depends on.
    Production callers pass the real implementation; tests pass a mock
    that records calls and returns canned results — the same
    dependency-injection seam kokoro_tts's Synthesizer Protocol uses."""

    def do_the_thing(self, payload: Any) -> dict[str, Any]:
        """Do the module's actual work. Returns a result dict; at minimum
        include an ``ok: bool``."""
        ...

    def shutdown(self) -> None:
        """Tear the engine down cleanly."""
        ...


class {{PackageName}}Node:  # (bases: Node — see the commented import above)
    """SUB <consumes topics> -> do the work -> PUB <produces topics>.

    The engine is dependency-injected so tests can substitute a mock
    without touching real hardware/models. Replace the placeholder
    __init__/setup/tick/teardown/health bodies below with this module's
    real bus contract.
    """

    def __init__(
        self,
        *,
        bus: Any,
        engine: Engine,
        name: str = "{{package_name}}",
        queue_maxsize: int = 32,
        install_signal_handlers: bool = False,
    ) -> None:
        # super().__init__(bus=bus, name=name,
        #                   install_signal_handlers=install_signal_handlers)
        self.bus = bus
        self.name = name
        self.engine = engine
        self._pending: "queue.Queue[Any]" = queue.Queue(maxsize=queue_maxsize)

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        """Subscribe to this module's consumed topics. Called once."""
        # self.bus.subscribe(topics.ACT_{{PACKAGE_NAME}}, self._on_command)
        pass

    def tick(self) -> None:
        """Drain one queued request per tick. Keep synthesis/inference/IO
        work here, never in the subscriber callback — see module
        docstring's threading rule."""
        try:
            msg = self._pending.get(timeout=0.1)
        except queue.Empty:
            return
        self._handle(msg)

    def teardown(self) -> None:
        """Unsubscribe + shut the engine down. Called once, on stop."""
        try:
            if self.engine is not None:
                self.engine.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def health(self) -> dict[str, Any]:
        """Queryable at any time; returned opaque to the supervisor."""
        return {"name": self.name, "queue_depth": self._pending.qsize()}

    # ── subscriber + worker ──────────────────────────────────────

    def _on_command(self, msg: Any) -> None:
        """Called on the bus delivery thread — must return quickly.
        Enqueue only; tick() does the real work."""
        try:
            self._pending.put_nowait(msg)
        except queue.Full:
            self._publish_result(msg, ok=False, reason="queue full")

    def _handle(self, msg: Any) -> None:
        try:
            result = self.engine.do_the_thing(msg)
        except Exception as exc:  # noqa: BLE001
            self._publish_result(
                msg, ok=False, reason=f"{type(exc).__name__}: {exc}",
            )
            return
        self._publish_result(msg, ok=bool(result.get("ok", False)))

    def _publish_result(
        self, request: Any, *, ok: bool, reason: str | None = None,
    ) -> None:
        # self.bus.publish(topics.Sense{{PackageName}}Result(
        #     ok=ok, reason=reason, node_id=self.name,
        # ))
        pass


def make_{{package_name}}_node(bus: Any, config: dict) -> "{{PackageName}}Node":
    """The module.yaml `factory:` entrypoint. Builds a live node wired to
    a real (but not-yet-warmed) engine — no model load, no hardware I/O
    at construction time; that's what setup()/first tick() are for."""
    engine = _build_engine(config)
    return {{PackageName}}Node(bus=bus, engine=engine)


def _build_engine(config: dict) -> Engine:
    """Replace with real engine construction, reading from
    {{PackageName}}Config (config.py.example) as needed."""
    raise NotImplementedError(
        "wire this to the module's real engine before shipping"
    )
