"""Resolved application configuration snapshot.

Historical M1.1 requirement: create immutable ``StatePaths`` values and a
resolved application configuration snapshot using the existing serialized
configuration as input.

``ResolvedRuntimeConfig`` here is deliberately NOT the same thing as
:class:`jaeger_ai.core.instance.schemas.RuntimeConfig` — that existing name
already means something else (per-format inference-engine selection:
``gguf_engine`` / ``mlx_engine``, persisted inside ``Config.runtime``). This
separation was identified by the historical release-audit A05. This module's
``ResolvedRuntimeConfig`` is the *whole-application* snapshot: where state
lives (:class:`~jaeger_ai.core.instance.instance.StatePaths`) plus a
point-in-time, defensively-copied view of the loaded, validated
:class:`~jaeger_ai.core.instance.schemas.Config` — captured once so that a
long-running operation (an admitted request, a resident runtime's startup
args) cannot be perturbed by a later, unrelated live edit to the operator's
mutable ``Config`` object.

This is NOT a replacement for supported live configuration changes. The
TUI's ``/voice`` command (see ``schemas.VoiceConfig``) and other live
editors keep mutating their own ``Config`` object and persisting it to
``config.yaml`` exactly as before; capturing a ``ResolvedRuntimeConfig``
only freezes one caller's view of it, deep-copied at that instant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from jaeger_ai.core.instance.instance import StatePaths
from jaeger_ai.core.instance.schemas import Config


@dataclass(frozen=True)
class ResolvedRuntimeConfig:
    """Immutable snapshot: resolved state paths + a defensively-copied
    ``Config``, captured at one instant.

    Frozen at the dataclass level is not by itself sufficient — a frozen
    wrapper around a *mutable* nested ``Config`` object would let a caller
    holding a reference to the original ``Config`` (or to this snapshot's
    ``config`` field) mutate it out from under every holder of the
    snapshot. :meth:`capture` closes that gap with ``Config.model_copy
    (deep=True)``; construct instances directly only when the ``config``
    passed in is already known to be exclusively owned (e.g. freshly
    loaded from disk and never handed to a live editor).
    """

    state_paths: StatePaths
    config: Config
    captured_at: float = field(default_factory=time.time)

    @classmethod
    def capture(cls, config: Config, state_paths: StatePaths) -> "ResolvedRuntimeConfig":
        """Take a defensive deep copy of ``config``. Mutating the caller's
        original ``config`` object after this call does not change the
        returned snapshot. ``state_paths`` is already immutable (a frozen
        dataclass of ``Path``/``str`` values) and is referenced as-is."""
        return cls(state_paths=state_paths, config=config.model_copy(deep=True))


__all__ = ["ResolvedRuntimeConfig"]
