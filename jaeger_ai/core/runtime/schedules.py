"""JaegerAI-owned schedule CRUD for the ARES WebUI adapter.

Jobs live in the instance SQLite store and are fired by the bridge
``CronRunner``. ARES never writes this database; it talks through
bridge query/command.
"""

from __future__ import annotations

from typing import Any


def list_jobs(*, include_paused: bool = True) -> dict[str, Any]:
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.memory.memory import _schedule_row_to_dict

    try:
        conn = sqlite_store.connection()
    except RuntimeError:
        return {"count": 0, "schedules": []}
    statuses = ("active", "paused") if include_paused else ("active",)
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
) -> dict[str, Any]:
    from jaeger_agent.tools.scheduling import schedule_prompt

    result = schedule_prompt(
        cron_expr=schedule,
        prompt=prompt,
        name=name,
        at=at,
    )
    if not result.get("scheduled"):
        raise ValueError(str(result.get("error") or "schedule failed"))
    if deliver:
        try:
            from jaeger_agent.workspace import get_layout

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
    from jaeger_agent.tools.scheduling import cancel_schedule

    return {"cancelled": bool(cancel_schedule(name)), "name": name}


def _set_status(name: str, status: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    from jaeger_agent.memory import sqlite_store

    with sqlite_store.writer() as conn:
        cur = conn.execute(
            "UPDATE schedules SET status = ? WHERE schedule_id = ? "
            "AND status IN ('active', 'paused')",
            (status, name),
        )
        return cur.rowcount > 0


def pause_job(name: str) -> dict[str, Any]:
    return {"paused": _set_status(name, "paused"), "name": name}


def resume_job(name: str) -> dict[str, Any]:
    return {"resumed": _set_status(name, "active"), "name": name}


__all__ = [
    "cancel_job",
    "create_job",
    "list_jobs",
    "pause_job",
    "resume_job",
]
