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


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="scheduling", operation="schedule_prompt",
    summary="schedule a prompt for autonomous execution",
)
def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict[str, Any]:
    """Schedule a prompt for unattended execution on a cron expression.

    Gated at WRITE_LOCAL: a scheduled prompt mutates durable on-disk
    state AND will fire autonomously later. Effects-of-effects matter
    here — a scheduled "open Safari + email me the news" turn can run
    while the operator is asleep, so the creation step asks for
    confirmation up front. (Each fired run is itself a fresh turn that
    re-passes through the tier ladder for its own tool calls.)

    BEFORE calling this with a relative or absolute time ("in 5 minutes",
    "at 10:20", "tomorrow at 7am"), call ``get_time`` first so the cron
    expression you build is anchored to the real current wall time.
    Guessing the time from chat context drifts.

    Disambiguate one-shot vs recurring:
      * "in N minutes" / "at HH:MM" / "at 10:20" — ONE-SHOT intent.
        Build ``M H D Mon *`` (specific minute, hour, day-of-month,
        month). The user will need to cancel afterwards; the
        framework has no native one-shot primitive yet.
      * "every N minutes" — RECURRING. Use ``*/N * * * *``. NB
        ``*/5 * * * *`` fires on the clock's 5-minute marks
        (00, 05, 10, …), NOT five minutes from now.

    `cron_expr` is standard 5-field cron — e.g. "0 7 * * *" (7am daily),
    "*/10 * * * *" (every 10 minutes), "25 22 26 5 *" (one-shot at
    22:25 on May 26th). The scheduled prompt fires in the same agent
    loop a fresh user turn would; tool results, memory updates, and
    TTS all behave the same.
    """
    try:
        row = mem.add_schedule(cron_expr=cron_expr, prompt=prompt, name=name)
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
