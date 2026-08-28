"""JaegerOS ``slot: mind`` node backed by an injected agent runtime."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from jaeger_os.nodes.base import Node

from .bridge import AgentBridge
from .contracts import AgentRuntime

RuntimeFactory = Callable[..., AgentRuntime]

#: Used when nothing else is named. Kept as a string (not an import) so
#: the optional provider SDKs stay unimported until a node actually boots.
DEFAULT_RUNTIME_FACTORY = "jaeger_agent.runtime:create_runtime"


def resolve_runtime_factory(target: str | RuntimeFactory) -> RuntimeFactory:
    """Resolve ``package.module:function`` while also supporting direct injection."""

    if callable(target):
        return target
    module_name, separator, attribute = str(target).partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("runtime_factory must use 'package.module:function' form")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise TypeError(f"runtime factory {target!r} is not callable")
    return factory


class MindNode(Node):
    """Supervised JaegerOS node that exposes one reusable agent brain."""

    def __init__(
        self,
        *,
        bus: Any,
        config: Mapping[str, Any] | None = None,
        runtime: AgentRuntime | None = None,
        runtime_factory: str | RuntimeFactory | None = None,
        name: str = "mind",
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self.config = dict(config or {})
        self.runtime = runtime
        self.runtime_factory = runtime_factory or self.config.get("runtime_factory")
        self.bridge: AgentBridge | None = None

    def setup(self) -> None:
        if self.runtime is None:
            # No factory named → the module's own config-built runtime.
            # That default is what lets an application declare the mind
            # slot and get a brain without writing any glue; apps owning
            # their own model pipeline name their factory instead.
            factory = resolve_runtime_factory(
                self.runtime_factory or DEFAULT_RUNTIME_FACTORY
            )
            self.runtime = factory(bus=self.bus, config=dict(self.config))
        self.bridge = AgentBridge(
            bus=self.bus,
            runtime=self.runtime,
            publish=self.bus.publish,
            subscribe=self.bus.subscribe,
            unsubscribe=self.bus.unsubscribe,
            session_key=str(self.config.get("session_key", "default")),
            max_queue=int(self.config.get("max_queue", 32)),
        )
        self.bridge.start()

    def teardown(self) -> None:
        if self.bridge is not None:
            try:
                self.bridge.close()
            except Exception as exc:  # noqa: BLE001 - teardown is best effort
                self._error = exc
        if self.runtime is not None:
            try:
                close_fn = getattr(self.runtime, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                pass

    def health(self) -> dict[str, Any]:
        result = super().health()
        if self.bridge is not None:
            result.update(self.bridge.health())
        return result


def make_mind_node(bus: Any, config: dict[str, Any]) -> MindNode:
    """JaegerOS module factory: ``(bus, config) -> MindNode``."""

    return MindNode(bus=bus, config=config)


__all__ = [
    "DEFAULT_RUNTIME_FACTORY",
    "MindNode",
    "make_mind_node",
    "resolve_runtime_factory",
]
