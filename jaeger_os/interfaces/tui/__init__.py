"""Jaeger-OS TUI — hermes-agent-inspired terminal interface.

A focused interactive surface for `python -m jaeger_os.interfaces.tui`.
Replaces the bare-bones jaeger CLI chat loop with:

  * ASCII banner + identity at boot
  * Tool catalog grouped by category
  * Status panel — version, instance name, model, session, uptime
  * Slash commands (`/help`, `/quit`, `/tools`, `/facts`, `/reset`)
  * Inline tool-activity display per turn
  * Status bar with live ruminating indicator + counters

Modeled after Nous Research's hermes-agent TUI (see screenshot
discussion 2026-05-19). Not a port of their code — independent
implementation using Rich. Parallel implementation to
:mod:`lilith.interfaces.tui`; both packages ship the same
hermes-agent-shaped surface so users get the same look regardless
of which framework they're driving.
"""

from __future__ import annotations

from typing import Any

from .app import JaegerTUI, run

__all__ = ["JaegerTUI", "run", "run_surface"]


def run_surface(ctx: Any, spec: Any) -> Any:
    """Chassis Surface factory (jaeger.toml ``[[surface]] tui``).

    J5A stub — declared so the format-0.1 manifest validator's
    ``factory`` field resolves to a callable. The chassis (today)
    only dispatches ``event_loop = "qt" | "none"``; JROS's TUI is
    its own loop launched directly by launch.py. J5B routes the
    manifest to ``event_loop = "none"`` so the chassis boots
    instance/bus/supervisor + atexit teardown, then returns control
    so JROS keeps owning the TUI loop.
    """
    raise NotImplementedError(
        "JROS TUI surface is launched directly by launch.py; the "
        "format-0.1 chassis sets event_loop = 'none' and returns "
        "after boot, leaving the TUI loop to JROS. This stub exists "
        "so jaeger.toml's [[surface]] tui factory resolves; it is "
        "never invoked at boot."
    )
