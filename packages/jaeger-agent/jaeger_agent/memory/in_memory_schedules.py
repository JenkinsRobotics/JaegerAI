"""In-memory ScheduleStore — the contract test reference."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class InMemoryScheduleStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def add(
        self,
        cron_expr: str,
        prompt: str,
        *,
        name: str | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        cron_expr = (cron_expr or "").strip()
        if not prompt or not (cron_expr or at):
            raise ValueError("prompt and (cron_expr or at) are required")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        key = (name or f"sched_{len(self._rows) + 1}").strip()
        row = {
            "name": key,
            "cron": "@once" if at else cron_expr,
            "prompt": prompt,
            "created_at": now,
            "next_run_at": at or now,
            "last_run_at": None,
            "cancelled": False,
        }
        self._rows[key] = row
        return dict(row)

    def list(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows.values() if not row["cancelled"]]

    def cancel(self, name: str) -> bool:
        row = self._rows.get((name or "").strip())
        if row is None or row["cancelled"]:
            return False
        row["cancelled"] = True
        return True


__all__ = ["InMemoryScheduleStore"]
