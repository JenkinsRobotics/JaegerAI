"""Cron-style scheduling skills.

  • schedule_prompt(cron_expr, prompt, name) — add a recurring prompt
  • list_schedules()                         — see what's active
  • cancel_schedule(name)                    — remove one

Persisted in <instance>/memory/schedules.jsonl, fired by CronRunner.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.memory import memory as mem
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.agent.schemas.tool_registry import register_tool_from_function


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="scheduling", operation="schedule_prompt",
    summary="schedule a prompt for autonomous execution",
)
def schedule_prompt(cron_expr: str = "", prompt: str = "",
                    name: str | None = None,
                    in_minutes: float | None = None,
                    at: str | None = None) -> dict[str, Any]:
    """Schedule a prompt to fire later — once, or on a recurring cron.

    ONE-SHOT ("remind me in 5 minutes" / "at 22:45" / "tomorrow 7am"):
    pass ``in_minutes=5`` (relative — no date math needed) or
    ``at="2026-07-07T22:45"`` (ISO local time). It fires exactly once,
    then completes itself. Do NOT build a cron expression for one-shot
    intent — ``*/5 * * * *`` means EVERY 5 minutes, forever.

    RECURRING ("every morning at 7:30" / "every Friday 5pm"): pass a
    standard 5-field ``cron_expr`` — "30 7 * * *", "0 17 * * 5". For an
    absolute ``at`` or ``cron_expr``, call ``get_time`` first so the
    time is anchored to the real current wall clock.

    Gated at WRITE_LOCAL: a scheduled prompt mutates durable on-disk
    state AND will fire autonomously later. Effects-of-effects matter
    here — a scheduled "open Safari + email me the news" turn can run
    while the operator is asleep, so the creation step asks for
    confirmation up front. (Each fired run is itself a fresh turn that
    re-passes through the tier ladder for its own tool calls.)

    The scheduled prompt fires in the same agent loop a fresh user turn
    would; tool results, memory updates, and TTS all behave the same.
    """
    try:
        if in_minutes is not None:
            from datetime import datetime, timedelta
            when = (datetime.now().astimezone()
                    + timedelta(minutes=float(in_minutes)))
            at = when.isoformat(timespec="seconds")
        row = mem.add_schedule(cron_expr=cron_expr, prompt=prompt,
                               name=name, at=at)
    except Exception as exc:
        return {"scheduled": False, "error": str(exc)}
    return {"scheduled": True, **row}


def list_schedules() -> dict[str, Any]:
    """List every active scheduled prompt with its next-run timestamp.

    Read-only — stays at the default READ_ONLY tier (no decorator)."""
    rows = mem.list_schedules()
    return {"count": len(rows), "schedules": rows}


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="scheduling", operation="cancel_schedule",
    summary="cancel a scheduled prompt",
)
def cancel_schedule(name: str) -> dict[str, Any]:
    """Remove a previously-scheduled prompt by name.

    Gated at WRITE_LOCAL (matches ``schedule_prompt``) — a stray
    cancellation can silently break an automation the operator
    depends on, so it gets the same prompt-before-mutation treatment
    as creation."""
    ok = mem.cancel_schedule(name)
    return {"cancelled": ok, "name": name}


@register_tool_from_function(name="schedule_prompt")
def _t_schedule_prompt(cron_expr: str = "", prompt: str = "",
                       name: str | None = None,
                       in_minutes: float | None = None,
                       at: str | None = None) -> dict:
    """Schedule a prompt / reminder / timer. One-shot: in_minutes=N or
    at="ISO time" (fires once, completes itself). Recurring: cron_expr
    ("30 7 * * *"). Never use cron for one-shot intent."""
    return schedule_prompt(cron_expr=cron_expr, prompt=prompt, name=name,
                           in_minutes=in_minutes, at=at)


@register_tool_from_function(name="list_schedules")
def _t_list_schedules() -> dict:
    """List every active scheduled prompt."""
    return list_schedules()


@register_tool_from_function(name="cancel_schedule")
def _t_cancel_schedule(name: str) -> dict:
    """Cancel a previously-scheduled prompt by name."""
    return cancel_schedule(name=name)
