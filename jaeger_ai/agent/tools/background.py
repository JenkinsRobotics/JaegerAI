"""Background-process agent tools.

The long-running counterpart to ``run_python`` / ``run_in_venv``
(which are synchronous + capped). These start a process that outlives
the turn, then let the agent check on it later.

  • start_background(code, name)   — launch a detached Python process
  • list_background()              — every background process + status
  • check_background(process_id)   — one process's status + output
  • stop_background(process_id)    — terminate a running process
  • pending_background()           — drain unsurfaced completion events

``start_background`` / ``stop_background`` are gated at WRITE_LOCAL
(tier 1) — they spawn / kill processes inside the instance. The read
tools are tier-0.
"""

from __future__ import annotations

from typing import Any

from jaeger_ai.core.context import _require_layout
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_ai.agent.background import processes as _proc
from jaeger_os.core.tools.tool_registry import register_tool_from_function


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="background",
    operation="start_background",
    summary="launch a long-running background process",
)
def start_background(code: str, name: str = "") -> dict[str, Any]:
    """Launch Python code as a detached background process that
    OUTLIVES the current turn.

    Use this — not run_python / run_in_venv — for work that genuinely
    takes minutes or longer: a long render, a bot that stays connected,
    a watcher. The code runs against the instance venv (installed
    packages are visible). Returns a ``process_id`` — use
    check_background to monitor it, stop_background to end it. Output
    streams to the process's log; nothing is lost when the turn ends."""
    layout = _require_layout()
    return _proc.start_background(layout, code, name=name)


def list_background() -> dict[str, Any]:
    """List every background process for this instance with live status
    (running / exited / stopped, exit code, elapsed). Read-only."""
    layout = _require_layout()
    return _proc.list_background(layout)


def check_background(process_id: str, lines: int = 20) -> dict[str, Any]:
    """Status of one background process plus the last ``lines`` lines of
    its output (default 20, max 2000 — raise it to read fuller output).
    Use this to see whether a process you started is still running and
    what it produced. Read-only."""
    layout = _require_layout()
    return _proc.process_status(layout, process_id, lines=lines)


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="background",
    operation="stop_background",
    summary="terminate a running background process",
)
def stop_background(process_id: str) -> dict[str, Any]:
    """Terminate a running background process by id."""
    layout = _require_layout()
    return _proc.stop_background(layout, process_id)


def pending_background() -> dict[str, Any]:
    """Drain the queue of background tasks that finished since the last
    check. Each completion is surfaced AT MOST ONCE — once returned,
    that process won't appear again until it's restarted.

    Useful right after you started a long-running ``start_background``
    job and want to know when it finishes without polling
    ``check_background`` in a loop. Returns
    ``{completions: [...], count: N}`` — empty list when nothing
    new has finished. Read-only."""
    layout = _require_layout()
    completions = _proc.consume_pending_completions(layout)
    return {"completions": completions, "count": len(completions)}


@register_tool_from_function(name="start_background")
def _t_start_background(code: str, name: str = "") -> dict:
    """Launch Python code as a background process that OUTLIVES this
    turn. Use this — not run_python / run_in_venv (which are capped
    and synchronous) — for work that takes minutes or longer: a long
    render, a bot that stays connected, a watcher. Runs against the
    instance venv. Returns a process_id; monitor with
    check_background, end with stop_background."""
    return start_background(code=code, name=name)


@register_tool_from_function(name="list_background", side_effect="read")
def _t_list_background() -> dict:
    """List every background process with live status (running /
    exited / stopped, exit code, elapsed)."""
    return list_background()


@register_tool_from_function(name="check_background", side_effect="read")
def _t_check_background(process_id: str, lines: int = 20) -> dict:
    """Status of one background process + the last `lines` lines of
    its output (default 20, max 2000 — raise it for fuller output).
    Use it to see whether a process you started is still running and
    what it produced."""
    return check_background(process_id=process_id, lines=lines)


@register_tool_from_function(name="stop_background")
def _t_stop_background(process_id: str) -> dict:
    """Terminate a running background process by id."""
    return stop_background(process_id=process_id)


@register_tool_from_function(name="pending_background", side_effect="read")
def _t_pending_background() -> dict:
    """Drain the queue of background tasks that finished since the
    last check. Each completion is surfaced at most once. Returns
    ``{completions: [...], count: N}`` — empty when nothing new has
    finished. Faster than polling ``check_background`` in a loop."""
    return pending_background()
