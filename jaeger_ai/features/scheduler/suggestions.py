"""Stub suggestion catalog — fill from Hermes cron/suggestion_catalog later."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleSuggestion:
    id: str
    title: str
    prompt: str
    cron: str
    source: str = "stub"


def default_suggestions() -> list[ScheduleSuggestion]:
    """Small built-in list so the feature surface is non-empty."""
    return [
        ScheduleSuggestion(
            id="morning_brief",
            title="Morning brief",
            prompt="Summarize overnight inbox and calendar for today.",
            cron="0 7 * * *",
        ),
        ScheduleSuggestion(
            id="weekly_review",
            title="Weekly review",
            prompt="Draft a weekly review of open missions and blockers.",
            cron="0 16 * * 5",
        ),
    ]
