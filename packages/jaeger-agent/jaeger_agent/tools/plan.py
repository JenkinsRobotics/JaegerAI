"""``update_plan`` and ``wait`` — the two small planning primitives coding agents lean on.

``update_plan`` is deliberately **stateless**. The model sends the whole plan each
time; the tool validates it and returns it, and the Gateway publishes the result as a
``turn.plan`` event for the client to render. Because nothing is stored in this
process, two conversations running at once can never see each other's plan (the
session ``todo`` scratchpad is one store per process, which is only safe for a
single-session terminal).

``wait`` pauses for a bounded time and stops early when the turn is cancelled.
"""

from __future__ import annotations

import time
from typing import Any

from jaeger_agent.util.tool_interrupt import is_interrupted
from jaeger_os.core.tools.tool_registry import register_tool_from_function

_STATUSES = ("pending", "in_progress", "completed")
MAX_WAIT_S = 60.0


def normalize_plan(plan: list[dict[str, Any]] | None, explanation: str | None = None) -> dict[str, Any]:
    """Validated plan payload, or ``{"ok": False, "error": ...}``.

    Each step is ``{step, status}`` with status ``pending``, ``in_progress`` or
    ``completed``. At most one step may be in progress: a second one means the
    model lost track of what it is doing, and saying so is the correction.
    """
    if not isinstance(plan, list) or not plan:
        return {"ok": False, "error": "plan must be a non-empty list of {step, status}"}
    steps: list[dict[str, str]] = []
    for index, item in enumerate(plan, 1):
        if not isinstance(item, dict):
            return {"ok": False, "error": f"step {index} must be an object with step and status"}
        text = str(item.get("step") or item.get("content") or "").strip()
        status = str(item.get("status") or "pending").strip().lower().replace("-", "_").replace(" ", "_")
        if not text:
            return {"ok": False, "error": f"step {index} has no text"}
        if status not in _STATUSES:
            return {"ok": False, "error": f"step {index} status {status!r} is not one of {list(_STATUSES)}"}
        steps.append({"step": text, "status": status})
    if sum(1 for s in steps if s["status"] == "in_progress") > 1:
        return {"ok": False, "error": "only one step may be in_progress at a time"}
    counts = {s: sum(1 for x in steps if x["status"] == s) for s in _STATUSES}
    payload: dict[str, Any] = {"ok": True, "plan": steps, "summary": {"total": len(steps), **counts}}
    if explanation and str(explanation).strip():
        payload["explanation"] = str(explanation).strip()
    return payload


def wait_for(seconds: float, *, sleep=time.sleep, clock=time.monotonic) -> dict[str, Any]:
    """Pause up to ``MAX_WAIT_S`` seconds, returning early if the turn is cancelled."""
    try:
        requested = float(seconds)
    except (TypeError, ValueError):
        return {"ok": False, "error": "seconds must be a number"}
    if requested < 0:
        return {"ok": False, "error": "seconds must not be negative"}
    target = min(requested, MAX_WAIT_S)
    started = clock()
    while True:
        remaining = target - (clock() - started)
        if remaining <= 0:
            break
        if is_interrupted():
            return {"ok": True, "waited_s": round(clock() - started, 3), "interrupted": True}
        sleep(min(0.25, remaining))
    return {"ok": True, "waited_s": round(clock() - started, 3), "interrupted": False,
            "capped": requested > MAX_WAIT_S}


@register_tool_from_function(name="update_plan")
def _t_update_plan(plan: list[dict], explanation: str | None = None) -> dict:
    """Show the operator your plan and keep it current on multi-step work.
    Send the WHOLE plan each time as `plan`: a list of `{step, status}` where
    status is `pending`, `in_progress` or `completed`. Keep exactly one step
    `in_progress`, and mark it `completed` before starting the next. Use
    `explanation` for a one-line note on what changed. It only records and
    displays the plan; it does not do the work."""
    return normalize_plan(plan, explanation)


@register_tool_from_function(name="wait")
def _t_wait(seconds: float) -> dict:
    """Pause for up to 60 seconds (e.g. wait for a build, a server to start, or
    a background job to progress) instead of polling in a tight loop. Stops
    early if the turn is cancelled."""
    return wait_for(seconds)
