"""ScheduleStore — replaceable persistence for SI cron prompts.

Jaeger remains authoritative when the bridge is up. ARES lists the
same rows as a projection; it does not own the table.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ScheduleStore(Protocol):
    def add(
        self,
        cron_expr: str,
        prompt: str,
        *,
        name: str | None = None,
        at: str | None = None,
    ) -> dict[str, Any]: ...

    def list(self) -> list[dict[str, Any]]: ...

    def cancel(self, name: str) -> bool: ...


__all__ = ["ScheduleStore"]
