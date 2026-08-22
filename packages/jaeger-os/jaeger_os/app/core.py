"""Core — the Tier-1 main-thread host role.

A first-class runtime role, distinct from **Node** (a supervised worker) and
**Surface** (a GUI shell). A Core:

  - **initializes on the OS main thread** (enforced in ``__init__``), during
    boot, after the bus and BEFORE nodes and surfaces;
  - is **identity-critical** — not supervised, no restart policy; if it dies,
    the app is down;
  - **talks over the bus** like everything else (surfaces reach it only via the
    bus, never by import).

This role exists because a heavy in-process core — a local LLM/agent brain —
can be neither a node (which runs on a worker thread, violating GPU/Metal
main-thread init) nor a surface (logic must not live in the GUI). The chassis
builds exactly one Core (the manifest ``[core]``) at the "init core" boot
phase, on the main thread. Heavy work then runs on the Core's OWN worker thread
(init on the main thread, generate on a worker, under the core's own lock).

See ``docs/JAEGER_APP_FORMAT.md`` (§ Core) and ``docs/TIER1_HOST_CORE.md``.
"""

from __future__ import annotations

import abc
import threading
from typing import Any


class CoreMainThreadError(RuntimeError):
    """A Tier-1 core was constructed off the OS main thread — it cannot be a
    worker node. Build it in the chassis ``init_core`` phase (main thread)."""


class Core(abc.ABC):
    """The Tier-1 host/core contract. Subclass and provide ``setup`` / ``stop``.

    Construction asserts the OS main thread; that assertion is the format's
    proof the core is not a worker node."""

    def __init__(self, *, bus: Any) -> None:
        if threading.current_thread() is not threading.main_thread():
            raise CoreMainThreadError(
                "Tier-1 core must initialize on the OS main thread "
                "(it is not a worker node)"
            )
        self.bus = bus

    def setup(self) -> None:
        """Subscribe to the bus and spin up the core's own work thread. Called
        by the chassis on the main thread, after the bus exists and before
        nodes/surfaces. Override."""

    def stop(self) -> None:
        """Stop accepting work, drain anything in flight, release resources.
        Called on shutdown BEFORE the bus closes. Idempotent. Override."""

    def health(self) -> dict[str, Any]:
        """Optional introspection (state, queue depth, last error, …)."""
        return {}


__all__ = ["Core", "CoreMainThreadError"]
