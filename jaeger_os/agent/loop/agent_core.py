"""AgentCore — JROS's Tier-1 core (the chassis ``[core]`` role).

The windowed app (bare ``./launch``) boots through the chassis
``JaegerApp``. At the ``init_core`` boot phase the chassis builds this
core on the OS **main thread** (Metal-safe), then hands the main thread
to the Qt surfaces' event loop. The boot order host.py used to express
by hand is now the format's:

    init_core   → AgentCore(bus) loads the agent/model on the MAIN thread
    setup()     → start the AgentBridge (its OWN worker thread)
    start_surfaces → Qt window + tray attach over the bus; qt.exec() owns
                     the main loop
    shutdown    → stop() drains the in-flight turn, THEN tears the model
                  down (never cleanup() a model mid-inference)

It is identity-critical (Tier-1): if it dies, the app is down — so it is
a ``[core]``, **not** a supervised node. No surface imports the agent;
they speak ``jaeger_os.core.messages`` only (the GUI/logic-separation
rule), so PySide6 is a swappable detail.
"""

from __future__ import annotations

import sys
from typing import Any

from jaeger_os.agent.loop.bridge import AgentBridge
from jaeger_os.app.core import Core

# How long to let an in-flight turn finish on quit before tearing the
# model down anyway (the process is exiting regardless). Bounded so a
# hung turn can't wedge quit forever; generous so a normal turn drains.
_TURN_DRAIN_TIMEOUT_S = 30.0


class AgentCore(Core):
    """Loads the agent/model on the OS main thread (``Core.__init__``
    carries the main-thread assertion — constructing this off-main is the
    proof it isn't a worker node), then bridges the bus to the real turn
    via :class:`AgentBridge` on the bridge's own worker thread. The
    pipeline's ``llm_lock`` inside the turn serializes model access."""

    def __init__(self, *, bus: Any, instance_name: str | None = None,
                 with_memory: bool = True, warmup: bool = False,
                 **_: Any) -> None:
        super().__init__(bus=bus)            # asserts the OS main thread
        print("[jros] booting the windowed app — loading the agent…",
              file=sys.stderr, flush=True)
        from jaeger_os.main import boot_for_tui
        # instance_name=None → boot_for_tui resolves default_instance_name()
        # (JAEGER_INSTANCE_NAME), set by main.py (run.sh) or launch.py (dev).
        # warmup=False skips the heavy VOICE-model preloads (whisper / kokoro)
        # — the windowed app is text chat with no voice, so warming them is
        # wasted work + a Metal-OOM risk. But the LLM KV-cache prewarm is
        # SEPARATE (prewarm_model, default on): it primes the system prompt +
        # tool schemas synchronously at boot so the FIRST user turn is instant
        # instead of a ~26s cold prefill. Boot takes ~60s longer; the first
        # turn earns it. (JAEGER_FAST_BOOT=1 skips prewarm's heavy Pass 2.)
        self.boot = boot_for_tui(
            instance_name=instance_name, with_memory=with_memory,
            warmup=warmup, prewarm_model=True)
        self.agent_name = _agent_name()
        self.bridge: AgentBridge | None = None

    def setup(self) -> None:
        """Main-thread caller; spin up the bridge's own worker thread."""
        self.bridge = AgentBridge(bus=self.bus, client=self.boot.client)
        self.bridge.start()
        print("[jros] windowed app ready.", file=sys.stderr, flush=True)

    def stop(self) -> None:
        """Drain the in-flight turn, THEN tear the model down. Runs in
        chassis shutdown, after surfaces close and before the bus does."""
        if self.bridge is not None:
            try:
                self.bridge.stop()
                self.bridge.join(timeout=_TURN_DRAIN_TIMEOUT_S)
            except Exception:  # noqa: BLE001 — teardown never raises
                pass
        if self.boot is not None:
            try:
                self.boot.cleanup()
            except Exception:  # noqa: BLE001
                pass

    def health(self) -> dict[str, Any]:
        return self.bridge.health() if self.bridge is not None else {}


def _agent_name() -> str:
    """The agent's display name for the window/tray title — the live
    ``identity.yaml`` ``name`` (a separate file from ``config.yaml``);
    'agent' only if the identity isn't reachable."""
    try:
        from jaeger_os.core.instance.schemas import Identity, load_yaml
        from jaeger_os.main import _pipeline
        layout = _pipeline.get("layout")
        if layout is not None:
            from jaeger_os.personality.character import active_character
            ch = active_character(layout.root)
            if ch is not None and ch.name:
                return str(ch.name)
            name = load_yaml(layout.identity_path, Identity).name
            if name:
                return str(name)
    except Exception:  # noqa: BLE001
        pass
    return "agent"


def make_core(bus: Any, config: dict[str, Any]) -> AgentCore:
    """Chassis ``[core]`` factory: ``make_core(bus, config) -> Core``."""
    return AgentCore(bus=bus, **config)


__all__ = ["AgentCore", "make_core"]
