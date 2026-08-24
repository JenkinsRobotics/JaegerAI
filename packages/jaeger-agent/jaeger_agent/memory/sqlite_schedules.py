"""SQLite ScheduleStore — production adapter over ``schedules`` in state.db."""

from __future__ import annotations

from typing import Any

from jaeger_agent.memory import memory as _mem


class SqliteScheduleStore:
    def add(
        self,
        cron_expr: str,
        prompt: str,
        *,
        name: str | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        return _mem.add_schedule(cron_expr, prompt, name=name, at=at)

    def list(self) -> list[dict[str, Any]]:
        return _mem.list_schedules()

    def cancel(self, name: str) -> bool:
        return _mem.cancel_schedule(name)


__all__ = ["SqliteScheduleStore"]
