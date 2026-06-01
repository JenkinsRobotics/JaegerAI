"""Lean runtime health probe.

A fast (<3s wall) idempotent smoke test the agent runs to verify
its own surface: layout writable, memory round-trip, file sandbox,
core tools registered, drift parser parses, skills discovered.

This is the *runtime* counterpart to ``--doctor``:

  * ``--doctor`` answers "are my **dependencies** ready?" (pip pkgs,
    PortAudio, config.yaml parse, model.path exists)
  * ``system_health`` answers "is the **agent** actually working?"
    (does memory round-trip, does the sandbox accept writes, does
    every CORE tool resolve in the registry)

A failing dep check would have prevented boot; a failing health
check means boot succeeded but something is broken at runtime —
distinct failure surface, hence the separate tool.

Each check is a callable returning ``(ok, detail, elapsed_ms)``;
``run_health_checks`` collects them and rolls up a summary. Designed
to be safely runnable from any context: agent tool, cron job, TUI
status panel, future external monitoring.
"""

from .probe import HealthCheck, HealthResult, run_health_checks  # noqa: F401

__all__ = ["HealthCheck", "HealthResult", "run_health_checks"]
