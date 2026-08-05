"""Compatibility factory for JaegerAI's former in-application mind module.

The reusable node now lives in :mod:`jaeger_agent`.  This wrapper preserves
the old import target during the 0.10 migration and supplies JaegerAI's
concrete runtime adapter.
"""

from __future__ import annotations

from typing import Any

from jaeger_agent import MindNode as _MindNode


class MindNode(_MindNode):
    """JaegerAgent node preconfigured with the JaegerAI product runtime."""

    def __init__(
        self,
        *,
        bus: Any,
        instance_name: str | None = None,
        with_memory: bool = True,
        warmup: bool = False,
        name: str = "mind",
        install_signal_handlers: bool = False,
    ) -> None:
        self._instance_name = instance_name
        self._with_memory = with_memory
        self._warmup = warmup
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
            runtime_factory="jaeger_ai.core.mind_runtime:create_runtime",
            config={
                "instance_name": instance_name,
                "with_memory": with_memory,
                "warmup": warmup,
                "prewarm_model": True,
            },
        )

    @property
    def boot(self) -> Any:
        return getattr(self.runtime, "boot", None)


def make_mind_node(bus: Any, config: dict[str, Any]) -> MindNode:
    return MindNode(
        bus=bus,
        instance_name=config.get("instance_name"),
        with_memory=bool(config.get("with_memory", True)),
        warmup=bool(config.get("warmup", False)),
    )


__all__ = ["MindNode", "make_mind_node"]
