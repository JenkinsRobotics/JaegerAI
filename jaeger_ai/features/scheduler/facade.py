"""Thin façade over existing schedule + delivery modules."""

from __future__ import annotations

from typing import Any


class SchedulerFacade:
    """Product API that wraps core schedule CRUD without owning storage."""

    def list_jobs(self, *, include_paused: bool = True) -> dict[str, Any]:
        from jaeger_ai.core.runtime import schedules

        return schedules.list_jobs(include_paused=include_paused)

    def create_job(self, **kwargs: Any) -> dict[str, Any]:
        from jaeger_ai.core.runtime import schedules

        return schedules.create_job(**kwargs)

    def cancel_job(self, name: str) -> dict[str, Any]:
        from jaeger_ai.core.runtime import schedules

        return schedules.cancel_job(name)

    def pause_job(self, name: str) -> dict[str, Any]:
        from jaeger_ai.core.runtime import schedules

        return schedules.pause_job(name)

    def resume_job(self, name: str) -> dict[str, Any]:
        from jaeger_ai.core.runtime import schedules

        return schedules.resume_job(name)

    def remember_delivery(
        self, layout: Any, name: str, *, channel: str, recipient: str
    ) -> dict[str, str]:
        from jaeger_ai.core.runtime import cron_delivery

        return cron_delivery.remember(layout, name, channel=channel, recipient=recipient)

    def lookup_delivery(self, layout: Any, name: str) -> dict[str, str] | None:
        from jaeger_ai.core.runtime import cron_delivery

        return cron_delivery.lookup(layout, name)


def get_scheduler() -> SchedulerFacade:
    return SchedulerFacade()
