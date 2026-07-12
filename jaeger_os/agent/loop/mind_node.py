"""mind_node.py — the Mind as a supervised chassis Node.

0.9 step 3 (mind-as-module, dev/docs/vision/THREE_TIER_STRUCTURE.md):
this makes the Mind LOADABLE through the same module system every
engine module (kokoro_tts, whisper_stt, animation, media) already
uses — ``discover_modules()`` finds ``jaeger_os/agent/module.yaml``
(``slot: mind``) and this factory boots it. It does **not** change the
default boot path: the windowed/TUI apps still boot through
:class:`jaeger_os.agent.loop.agent_core.AgentCore` (a chassis
``[core]`` — main-thread, Tier-1, not supervisor-restartable). Adoption
of THIS factory as the real boot root is a later step (the repo
split), once a manifest actually declares a ``slot = "mind"`` node.

Why a separate wrapper instead of reusing ``AgentCore``: the module
system's ``ThreadHandle`` supervises ``jaeger_os.nodes.base.Node``
instances (setup/tick/teardown/state, started on a worker thread by
the supervisor). ``AgentCore`` is deliberately NOT a ``Node`` — it's
built on the OS main thread (Metal-safe) and isn't restartable in
isolation, matching its Tier-1 identity-critical role. ``MindNode``
wraps the SAME two calls ``AgentCore.__init__``/``setup()`` make
(``jaeger_os.main.boot_for_tui`` + :class:`~jaeger_os.agent.loop.bridge.AgentBridge`)
behind the ``Node`` contract instead, so the supervisor can discover,
start, stop, and health-check the Mind like any other module.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.nodes.base import Node


class MindNode(Node):
    """``Node`` wrapper around ``boot_for_tui`` + ``AgentBridge``.

    ``setup()`` does the real boot (loads the configured model,
    builds the system prompt, wires the agent) — this can take a long
    time for a local model, same as ``AgentCore`` today. The
    supervisor's ``ThreadHandle.start()`` only waits up to 5s for
    ``RUNNING``/``FAILED`` before returning; a slow model load simply
    continues on this node's own thread past that window, exactly the
    way a heavy engine module's warm-up already does — not a new
    failure mode this class introduces.
    """

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
        super().__init__(
            bus=bus, name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self._instance_name = instance_name
        self._with_memory = with_memory
        self._warmup = warmup
        self.boot: Any = None
        self.bridge: Any = None

    def setup(self) -> None:
        from jaeger_os.agent.loop.bridge import AgentBridge
        from jaeger_os.main import boot_for_tui

        self.boot = boot_for_tui(
            instance_name=self._instance_name,
            with_memory=self._with_memory,
            warmup=self._warmup,
            prewarm_model=True,
        )
        self.bridge = AgentBridge(bus=self.bus, client=self.boot.client)
        self.bridge.start()

    def teardown(self) -> None:
        # Mirrors AgentCore.stop() (agent/loop/agent_core.py): drain the
        # in-flight turn before tearing the model down, never the
        # reverse. Best-effort — teardown must never raise.
        if self.bridge is not None:
            try:
                self.bridge.stop()
                self.bridge.join(timeout=30.0)
            except Exception:  # noqa: BLE001
                pass
        if self.boot is not None:
            try:
                self.boot.cleanup()
            except Exception:  # noqa: BLE001
                pass

    def health(self) -> dict[str, Any]:
        out = super().health()
        if self.bridge is not None:
            out.update(self.bridge.health())
        return out


def make_mind_node(bus: Any, config: dict[str, Any]) -> MindNode:
    """Chassis-contract factory ``(bus, config) -> MindNode`` — the
    module system's entry point for ``slot: mind`` (see
    ``jaeger_os/agent/module.yaml``). Mirrors ``make_animation_node`` /
    ``make_audio_session_node``'s shape (``jaeger_os/nodes/*/__init__.py``)."""
    return MindNode(
        bus=bus,
        instance_name=config.get("instance_name"),
        with_memory=bool(config.get("with_memory", True)),
        warmup=bool(config.get("warmup", False)),
    )


__all__ = ["MindNode", "make_mind_node"]
