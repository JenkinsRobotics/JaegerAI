"""Scheduler feature façade.

Jaeger already persists schedules in agent memory SQLite and delivers via
``jaeger_ai.core.runtime.cron_delivery``. This package is the product home
for richer job/suggestion/incident patterns ported from Hermes ``cron/``,
without forking a second job database.
"""

from .facade import SchedulerFacade, get_scheduler

__all__ = ["SchedulerFacade", "get_scheduler"]
