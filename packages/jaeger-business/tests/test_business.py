"""Tests for standalone jaeger-business package."""

from __future__ import annotations

from pathlib import Path

from jaeger_business import BusinessStore, DEFAULT_TEAM_ROLES


def test_business_team_budgets_and_approval_gates(tmp_path: Path) -> None:
    store = BusinessStore(tmp_path, daily_spend_cap_usd=20.0)
    team = store.list_team()
    assert len(team) == len(DEFAULT_TEAM_ROLES) == 8
    assert store.check_action_requires_approval("publisher", "youtube_publish") is True
    assert store.check_action_requires_approval("researcher", "memory_recall") is False

    proj = store.create_project(name="JP01 Robotics YouTube", kind="youtube_channel", budget_usd=15.0)
    # Spend without owner approval is refused
    ok, reason = store.record_spend(project_id=proj.project_id, role_id="designer", amount_usd=5.0, description="Thumbnail font")
    assert ok is False and "approval" in reason

    # Spend with owner approval succeeds within cap
    ok2, _ = store.record_spend(
        project_id=proj.project_id,
        role_id="designer",
        amount_usd=10.0,
        description="Stock SFX",
        approved_by="owner",
    )
    assert ok2 is True

    # Spend over project budget is refused
    ok3, reason3 = store.record_spend(
        project_id=proj.project_id,
        role_id="designer",
        amount_usd=8.0,
        description="Over budget",
        approved_by="owner",
    )
    assert ok3 is False and "project_budget_exceeded" in reason3
    summary = store.budget_summary()
    assert summary["daily_spent_usd"] == 10.0
    assert summary["daily_remaining_usd"] == 10.0
