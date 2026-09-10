"""Tests for jaeger_ai.features.scheduler scaffold."""

from __future__ import annotations

from jaeger_ai.features.scheduler import SchedulerFacade, get_scheduler
from jaeger_ai.features.scheduler.suggestions import default_suggestions


def test_suggestions_nonempty():
    rows = default_suggestions()
    assert len(rows) >= 2
    assert rows[0].cron


def test_facade_list_jobs_without_store(monkeypatch):
    import jaeger_ai.core.runtime.schedules as schedules

    monkeypatch.setattr(schedules, "list_jobs", lambda include_paused=True: {"count": 0, "schedules": []})
    fac = get_scheduler()
    assert isinstance(fac, SchedulerFacade)
    assert fac.list_jobs()["count"] == 0
