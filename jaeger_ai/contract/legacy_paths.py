"""The switch that keeps every non-canonical execution path isolated.

A Jaeger turn has exactly one path: a client (IDE, WebUI, TUI, Mac app) admits it
to the Gateway, and the Gateway's resident Entity executes it and owns the
session record. Older paths still exist in the tree — the WebUI's in-process
agent, the ``:8791`` runner, the Hermes/OpenClaw/Roundtable profile routing, the
Gateway's native-MCP-first branch — and are kept, not deleted. They stay off
unless the operator opts back in with :data:`LEGACY_PATHS_ENV`.

Every isolated entry point asks :func:`legacy_paths_enabled` and, when it is off,
fails closed with :func:`disabled_reason` so the caller sees *why* nothing ran
instead of a silent fallback to a different executor.

Defined here, once, because two layers (Gateway and WebUI) both consult it.
"""
from __future__ import annotations

import os
from typing import Final

LEGACY_PATHS_ENV: Final = "JAEGER_LEGACY_PATHS"
"""Set to ``1``/``true``/``yes``/``on`` to re-enable the isolated execution paths."""

_TRUE: Final = frozenset({"1", "true", "yes", "on"})


def legacy_paths_enabled(environ: dict[str, str] | None = None) -> bool:
    """True only when the operator explicitly re-enabled the isolated paths."""
    source = os.environ if environ is None else environ
    return str(source.get(LEGACY_PATHS_ENV, "")).strip().lower() in _TRUE


HIDDEN_WEBUI_TABS: Final = frozenset({
    "tasks", "kanban", "skills", "memory", "profiles", "todos", "insights", "logs",
})
"""WebUI tabs that read the legacy Hermes systems, not Jaeger's, and so show empty or wrong
data (Hermes cron, its own kanban, memory files, skills index, todo list, usage analytics,
log files). Hidden unless the operator re-enabled the legacy paths: the WebUI counterpart
of the Mac app hiding its unfinished windows. ``chat``, ``workspaces`` and ``settings`` work."""

VISIBLE_WEBUI_PROFILES: Final = frozenset({"jaeger"})
"""The only agent profile a Gateway-only WebUI offers; hermes/openclaw/roundtable are
legacy runtimes (see :data:`LEGACY_PATHS_ENV`)."""


def disabled_reason(path: str) -> str:
    """The message an isolated entry point returns instead of running."""
    return (
        f"{path} is isolated: Jaeger turns run through the Gateway only. "
        f"Set {LEGACY_PATHS_ENV}=1 to re-enable it."
    )
