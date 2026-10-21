"""JaegerAI-owned schedule CRUD for the ARES WebUI adapter.

Jobs live in the instance SQLite store and are fired by the bridge
``CronRunner``. ARES never writes this database; it talks through
bridge query/command.
"""

from __future__ import annotations

from typing import Any


def list_jobs(*, include_paused: bool = True, include_cancelled: bool = False) -> dict[str, Any]:
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.memory.memory import _schedule_row_to_dict

    try:
        conn = sqlite_store.connection()
    except RuntimeError:
        return {"count": 0, "schedules": []}
    statuses = ("active", "paused") if include_paused else ("active",)
    if include_cancelled:
        statuses += ("cancelled",)
    placeholders = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT * FROM schedules WHERE status IN ({placeholders}) "
        "ORDER BY schedule_id",
        statuses,
    ).fetchall()
    jobs = []
    for row in rows:
        item = _schedule_row_to_dict(row)
        status = str(row["status"] or "active")
        item["status"] = status
        item["paused"] = status == "paused"
        jobs.append(item)
    return {"count": len(jobs), "schedules": jobs}


def create_job(
    *,
    prompt: str,
    schedule: str = "",
    name: str | None = None,
    at: str | None = None,
    deliver: str | None = None,
    recipient: str | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    # This is the explicit human-facing control plane, not an agent tool call.
    # The HTTP route is the user's confirmation, so invoking the decorated
    # ``schedule_prompt`` tool here would ask the headless bridge for a second
    # confirmation it cannot provide and hang the request. Persist through the
    # same memory owner directly; autonomous agent calls still use the
    # permission-gated tool.
    from jaeger_agent.memory import memory

    try:
        row = memory.add_schedule(
            cron_expr=schedule,
            prompt=prompt,
            name=name,
            at=at,
            **({"timezone_name": timezone_name} if timezone_name is not None else {}),
        )
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    result = {"scheduled": True, **row}
    if deliver:
        try:
            from jaeger_agent.core.workspace import get_layout

            from jaeger_ai.core.runtime import cron_delivery

            layout = get_layout()
            result["deliver"] = cron_delivery.remember(
                layout,
                str(result.get("name") or name or ""),
                channel=str(deliver),
                recipient=str(recipient or ""),
            )
        except Exception as exc:  # noqa: BLE001
            result["deliver_error"] = str(exc)
    return result


def cancel_job(name: str) -> dict[str, Any]:
    # As in ``create_job``, this path represents a direct human UI action. The
    # agent's cancel tool remains permission-gated; the controller calls the
    # durable memory owner without a redundant headless approval prompt.
    from jaeger_agent.memory import memory

    return {"cancelled": bool(memory.cancel_schedule(name)), "name": name}


def _set_status(name: str, status: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    from jaeger_agent.memory import sqlite_store

    with sqlite_store.writer() as conn:
        cur = conn.execute(
            "UPDATE schedules SET status = ?, config_revision = config_revision + 1 WHERE schedule_id = ? "
            "AND status IN ('active', 'paused')",
            (status, name),
        )
        return cur.rowcount > 0


def pause_job(name: str) -> dict[str, Any]:
    return {"paused": _set_status(name, "paused"), "name": name}


def resume_job(name: str) -> dict[str, Any]:
    return {"resumed": _set_status(name, "active"), "name": name}


def restore_job(name: str) -> dict[str, Any]:
    """Recover a cancelled definition paused; never schedule work as a side effect of restore."""
    from jaeger_agent.memory import sqlite_store
    with sqlite_store.writer() as conn:
        changed = conn.execute("UPDATE schedules SET status='paused', config_revision=config_revision+1 WHERE schedule_id=? AND status='cancelled'", ((name or '').strip(),)).rowcount
    return {"restored": bool(changed), "name": name}


__all__ = [
    "cancel_job",
    "create_job",
    "list_jobs",
    "pause_job",
    "resume_job",
]


def update_job(name: str, *, prompt: str, schedule: str, timezone_name: str | None = None,
               expected_revision: int | None = None) -> dict[str, Any]:
    """Edit configuration under the owner transaction; scheduler progress is independent."""
    from datetime import datetime, timezone
    from croniter import croniter
    from jaeger_agent.memory import sqlite_store, memory
    if not prompt.strip() or not croniter.is_valid(schedule):
        raise ValueError("A prompt and valid cron expression are required")
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise ValueError("A valid schedule revision is required")
    with sqlite_store.writer() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE schedule_id=? AND status IN ('active','paused')", (name,)).fetchone()
        if row is None:
            raise ValueError("Schedule not found or no longer editable")
        if expected_revision is not None and row['config_revision'] != expected_revision:
            raise ValueError("Schedule revision changed; refresh and review the saved definition")
        zone = memory.schedule_timezone(row['timezone'] if timezone_name is None else timezone_name)
        next_fire = croniter(schedule, datetime.now().astimezone(zone)).get_next(datetime).astimezone(timezone.utc).isoformat(timespec="seconds")
        conn.execute("UPDATE schedules SET cron=?, prompt=?, timezone=?, next_fire_at=?, config_revision=config_revision+1 WHERE schedule_id=?",
                     (schedule, prompt.strip(), zone.key if zone else None, next_fire, name))
        revision = row['config_revision'] + 1
    return {"updated": True, "name": name, "config_revision": revision}
