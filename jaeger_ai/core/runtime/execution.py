"""Execution mode — how long a request keeps running before it hands back.

Three independent axes govern a turn, and keeping them separate is the
whole point of this module:

  * :mod:`jaeger_ai.core.runtime.modes`     — WHICH BRAIN answers
    (``normal`` / ``high`` / ``deep-sleep``; a 60-90s model swap).
  * :mod:`jaeger_ai.core.runtime.autonomy`  — WHETHER IT ASKS before an
    outward / destructive action (``ask`` / ``scoped`` / ``auto``).
  * this module                             — HOW LONG IT KEEPS GOING
    before the turn ends and the prompt comes back.

The gap this closes: a big multi-step request ("go through every note in
every folder and distil the actions") would get five or six tool calls, a
narrated promise — *"Let me start by reading the first folder…"* — and
then the prompt came back. The work was announced, not done. Nothing in
the stack owned "the objective is not finished yet", because the agent
loop's exit door is per-TURN ("a reply with no tool calls is the final
answer") and the goal loop only runs when the user set a ``/goal``.

Four modes:

  ``interactive``  one turn per prompt — the classic behaviour, default.
  ``auto``         after each turn, a stall check (see
                   :mod:`jaeger_ai.core.runtime.continuation`) re-fires
                   the turn with a continuation directive until the work
                   is done, the step budget runs out, or the user stops
                   it. Also loosens ``autonomy`` to ``auto`` so the run
                   is not blocked on a confirm prompt nobody is watching.
  ``supervised``   same continuation engine, but ``autonomy`` is pinned
                   to ``ask`` — every mutation stops for a y/n.
  ``deepthink``    hands off to the existing Deep Think pipeline
                   (plan → execute → verify → settle); this module only
                   records that the session is in it.

State is process-global (one resident agent per instance) and switching
is INSTANT — no model swap. The autonomy coupling is remembered so
leaving ``auto`` / ``supervised`` restores whatever the user had before,
rather than silently leaving the confirm gate wide open.
"""

from __future__ import annotations

import os
import threading
import time
from enum import Enum


class ExecutionMode(str, Enum):
    """The four execution modes, as a value that is also its own name."""

    INTERACTIVE = "interactive"
    AUTO = "auto"
    SUPERVISED = "supervised"
    DEEPTHINK = "deepthink"


EXECUTION_MODES: tuple[str, ...] = tuple(m.value for m in ExecutionMode)
DEFAULT = ExecutionMode.INTERACTIVE.value

# Spellings the user is likely to type. ``normal`` is deliberately NOT
# here: it is a ``modes.py`` model preset, and the TUI's /mode routes it
# there. Aliasing it to ``interactive`` would make "/mode normal" mean
# two different things depending on which surface you typed it on.
_ALIASES: dict[str, str] = {
    "chat": "interactive",
    "standard": "interactive",
    "off": "interactive",
    "full-auto": "auto",
    "fullauto": "auto",
    "autonomous": "auto",
    "on": "auto",
    "step": "supervised",
    "stepwise": "supervised",
    "deep-think": "deepthink",
    "coder": "deepthink",
}

_DESC = {
    "interactive": "one turn per prompt; the agent answers and hands back",
    "auto": "keeps executing until the objective is done, the step budget "
            "runs out, or you /stop it",
    "supervised": "same continuous execution, but every mutation pauses "
                  "for approval",
    "deepthink": "staged plan → execute → verify → settle pipeline",
}

# The confirm-gate policy each mode implies. ``interactive`` restores
# whatever the user was on before the switch instead of forcing one.
_AUTONOMY_FOR = {"auto": "auto", "supervised": "ask"}

# Outer job budget (how many inner turns a run may take). Inner-turn
# tool fuse lives on ``inner_max()`` — hitting it continues, it does
# not finish the job.
DEFAULT_MAX_STEPS = 100
INNER_MAX_CHAT = 24
INNER_MAX_AUTO = 60

_lock = threading.RLock()
_state: dict[str, object] = {
    "mode": DEFAULT,
    "prior_autonomy": None,   # what to restore when leaving auto/supervised
    # Live run bookkeeping — set by begin_run, read by the status bar.
    "objective": "",
    "steps": 0,
    "budget": DEFAULT_MAX_STEPS,
    "started_at": 0.0,
    "phase": "",              # plan │ executing │ verifying │ done
    "active": False,
    "last_reason": "",
    "verified": False,   # the one verify pass has been spent
}

# Cooperative stop flag. /stop and Ctrl-C set it; the worker checks it
# before re-firing, so a run halts at a turn boundary with its partial
# work intact rather than being killed mid-tool.
_stop = threading.Event()


# ── mode ────────────────────────────────────────────────────────────


def current_mode() -> str:
    return str(_state["mode"])


def is_continuous() -> bool:
    """True when the mode wants the turn re-fired until the job is done."""
    return current_mode() in ("auto", "supervised")


def list_modes() -> list[str]:
    return list(EXECUTION_MODES)


def normalize(name: str) -> str | None:
    """Map user spelling → canonical mode, or ``None`` when unknown."""
    key = (name or "").strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in EXECUTION_MODES else None


def execution_info() -> dict:
    """Everything a surface needs to answer "what mode am I in?" — the
    mode, its description, and the live run progress when one is up."""
    mode = current_mode()
    info = {
        "mode": mode,
        "options": list(EXECUTION_MODES),
        "description": _DESC.get(mode, ""),
        "continuous": is_continuous(),
    }
    info.update(run_progress())
    return info


def set_execution_mode(name: str) -> dict:
    """Switch execution mode (instant, no model swap). Never raises.

    Coupling the confirm gate is the point: ``auto`` with the gate on
    ``ask`` would stall on the first write waiting for a human who
    thought they had just delegated the whole job.
    """
    target = normalize(name)
    if target is None:
        return {"ok": False,
                "error": f"unknown execution mode {name!r}; "
                         f"choose from {list(EXECUTION_MODES)}"}
    with _lock:
        previous = str(_state["mode"])
        if target == previous:
            return {"ok": True, "mode": target, "unchanged": True,
                    "autonomy": _current_autonomy()}
        _state["mode"] = target
        autonomy = _apply_autonomy(previous, target)
        if target == "interactive":
            end_run("mode switched to interactive")
    _publish()
    return {"ok": True, "mode": target, "previous": previous,
            "autonomy": autonomy, "description": _DESC.get(target, "")}


def _current_autonomy() -> str:
    try:
        from jaeger_ai.core.runtime.autonomy import current_autonomy
        return current_autonomy()
    except Exception:  # noqa: BLE001 — autonomy is advisory here
        return ""


def _apply_autonomy(previous: str, target: str) -> str:
    """Move the confirm gate to match the new mode; remember what to put
    back. Best-effort — a failure to move it must not block the switch."""
    try:
        from jaeger_ai.core.runtime.autonomy import (
            current_autonomy, set_autonomy,
        )
    except Exception:  # noqa: BLE001
        return ""
    want = _AUTONOMY_FOR.get(target)
    if want is None:
        restore = _state.get("prior_autonomy")
        _state["prior_autonomy"] = None
        if previous in _AUTONOMY_FOR and restore:
            set_autonomy(str(restore))
        return current_autonomy()
    if previous not in _AUTONOMY_FOR:
        # First step into a coupled mode — stash what the user had.
        _state["prior_autonomy"] = current_autonomy()
    set_autonomy(want)
    return current_autonomy()


def _publish() -> None:
    """Best-effort status broadcast so tray / chat header follow along."""
    try:
        from jaeger_ai.core.messages import ModeState
        from jaeger_ai.core.runtime import modes
        from jaeger_ai.core.runtime.autonomy import current_autonomy
        from jaeger_ai.main import _pipeline
        bus = _pipeline.get("chassis_bus")
        if bus is not None:
            bus.publish(ModeState(mode=modes.current_mode(),
                                  autonomy=current_autonomy()))
    except Exception:  # noqa: BLE001 — status is best-effort
        pass


# ── run bookkeeping ─────────────────────────────────────────────────


def max_steps() -> int:
    """Outer step budget for one job (``job_max_steps``).

    ``JAEGER_AUTO_MAX_STEPS`` wins (handy for a one-off long job or for
    pinning a test), then ``automation.job_max_steps`` (falling back to
    the deprecated ``auto_max_steps`` alias), then
    :data:`DEFAULT_MAX_STEPS`.
    """
    env = os.environ.get("JAEGER_AUTO_MAX_STEPS", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    try:
        from jaeger_ai.main import _pipeline
        cfg = _pipeline.get("config")
        auto = getattr(cfg, "automation", None)
        value = getattr(auto, "job_max_steps", 0) or getattr(
            auto, "auto_max_steps", 0)
        if value:
            return max(1, int(value))
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_MAX_STEPS


def inner_max(*, batch: bool = False) -> int:
    """Per-turn tool-call fuse.

    Chat uses ``automation.inner_max_iterations`` (default 24). Auto,
    batch, or an open ledger uses at least :data:`INNER_MAX_AUTO` (60)
    so a notes-scale job is not cut off mid-batch. Hitting this number
    continues the outer loop; it is not a job-complete signal.
    ``JAEGER_INNER_MAX`` overrides both.
    """
    env = os.environ.get("JAEGER_INNER_MAX", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    configured = INNER_MAX_CHAT
    try:
        from jaeger_ai.main import _pipeline
        cfg = _pipeline.get("config")
        value = getattr(getattr(cfg, "automation", None),
                        "inner_max_iterations", 0)
        if value:
            configured = max(1, int(value))
    except Exception:  # noqa: BLE001
        pass
    if batch or is_continuous():
        return max(configured, INNER_MAX_AUTO)
    return configured


def begin_run(objective: str = "", *, budget: int | None = None) -> dict:
    """Start (or restart) an autonomous run and clear any stop request."""
    with _lock:
        _stop.clear()
        _state.update({
            "objective": (objective or "").strip(),
            "steps": 0,
            "budget": int(budget) if budget else max_steps(),
            "started_at": time.time(),
            "phase": "plan" if objective else "executing",
            "active": True,
            "last_reason": "",
            "verified": False,
        })
    return run_progress()


def record_step(phase: str = "executing") -> int:
    """Count one continuation step; returns the new step number."""
    with _lock:
        if not _state["active"]:
            begin_run(str(_state.get("objective") or ""))
        _state["steps"] = int(_state["steps"]) + 1
        _state["phase"] = phase
        return int(_state["steps"])


def steps_left() -> int:
    with _lock:
        return max(0, int(_state["budget"]) - int(_state["steps"]))


def end_run(reason: str = "") -> dict:
    """Mark the run finished. Idempotent; keeps the counters for /status."""
    with _lock:
        _state["active"] = False
        _state["phase"] = "done"
        if reason:
            _state["last_reason"] = reason
        return run_progress()


def run_active() -> bool:
    with _lock:
        return bool(_state["active"])


def run_progress() -> dict:
    with _lock:
        started = float(_state["started_at"] or 0.0)
        return {
            "active": bool(_state["active"]),
            "objective": str(_state["objective"]),
            "step": int(_state["steps"]),
            "budget": int(_state["budget"]),
            "phase": str(_state["phase"]),
            "elapsed_s": (time.time() - started) if started else 0.0,
            "reason": str(_state["last_reason"]),
            "stopping": _stop.is_set(),
        }


def needs_verification() -> bool:
    """True when a run with a stated objective has claimed completion but
    has not yet been asked to check its own deliverables. Exactly one
    verify pass per run — a second would just re-read the same files."""
    with _lock:
        return bool(_state["active"]) and not bool(_state["verified"]) \
            and bool(_state["objective"])


def mark_verified() -> None:
    with _lock:
        _state["verified"] = True


def set_phase(phase: str) -> None:
    """Move the breadcrumb (``plan`` → ``executing`` → ``verifying`` →
    ``done``) without spending a step."""
    with _lock:
        _state["phase"] = phase


# ── stop ────────────────────────────────────────────────────────────


def request_stop(reason: str = "user stop") -> None:
    """Ask a running autonomous loop to halt at the next turn boundary."""
    _stop.set()
    with _lock:
        _state["last_reason"] = reason


def stop_requested() -> bool:
    return _stop.is_set()


def clear_stop() -> None:
    _stop.clear()


def stop_event() -> threading.Event:
    """The raw event, for callers that want to wait on it."""
    return _stop


def reset() -> None:
    """Full reset — tests and ``/new`` use this."""
    with _lock:
        _stop.clear()
        _state.update({
            "mode": DEFAULT, "prior_autonomy": None, "objective": "",
            "steps": 0, "budget": DEFAULT_MAX_STEPS, "started_at": 0.0,
            "phase": "", "active": False, "last_reason": "",
            "verified": False,
        })


__all__ = [
    "ExecutionMode", "EXECUTION_MODES", "DEFAULT", "DEFAULT_MAX_STEPS",
    "INNER_MAX_CHAT", "INNER_MAX_AUTO", "inner_max",
    "current_mode", "is_continuous", "list_modes", "normalize",
    "execution_info", "set_execution_mode", "max_steps", "begin_run",
    "record_step", "steps_left", "end_run", "run_active", "run_progress",
    "set_phase", "needs_verification", "mark_verified",
    "request_stop", "stop_requested", "clear_stop",
    "stop_event", "reset",
]
