"""Budget pacing engine, burn rate analysis, and remaining allowance projections."""

from __future__ import annotations

import calendar
import logging
from datetime import UTC, datetime
from typing import Any

from .models import CategoryBudget
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.budget")

PACING_WARNING_BUFFER = 0.15  # Alert if category spend is >15% ahead of elapsed month pace


class BudgetEngine:
    """Calculates budget status, burn rate, and projected end-of-month variances."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store

    def evaluate_pacing(
        self,
        month: str | None = None,
        reference_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Evaluate category pacing against the elapsed portion of the month."""
        now = reference_date or datetime.now(UTC)
        month_str = month or now.strftime("%Y-%m")

        _, days_in_month = calendar.monthrange(now.year, now.month)
        day_of_month = min(now.day, days_in_month)
        days_left = max(1, days_in_month - day_of_month)

        elapsed_ratio = day_of_month / float(days_in_month)
        elapsed_pct = round(elapsed_ratio * 100.0, 1)

        budgets = self.store.get_budgets(month=month_str)

        total_budgeted = 0.0
        total_actual = 0.0
        over_budget: list[dict[str, Any]] = []
        pacing_fast: list[dict[str, Any]] = []
        on_track: list[dict[str, Any]] = []

        for b in budgets:
            total_budgeted += b.budgeted
            total_actual += b.actual

            if b.budgeted <= 0:
                continue

            spent_ratio = b.actual / b.budgeted
            spent_pct = round(spent_ratio * 100.0, 1)
            remaining = round(b.budgeted - b.actual, 2)
            daily_remaining = round(remaining / days_left, 2) if remaining > 0 else 0.0

            # Current daily run rate and projected end-of-month spend
            daily_run_rate = b.actual / day_of_month if day_of_month > 0 else 0.0
            projected_spend = round(daily_run_rate * days_in_month, 2)
            projected_variance = round(projected_spend - b.budgeted, 2)

            item = {
                "category": b.category,
                "budgeted": b.budgeted,
                "actual": b.actual,
                "remaining": remaining,
                "spent_pct": spent_pct,
                "daily_allowance_remaining": daily_remaining,
                "projected_spend": projected_spend,
                "projected_variance": projected_variance,
            }

            if b.actual > b.budgeted:
                item["over_by"] = round(b.actual - b.budgeted, 2)
                item["status"] = "over_budget"
                over_budget.append(item)
            elif spent_ratio > (elapsed_ratio + PACING_WARNING_BUFFER):
                item["status"] = "pacing_fast"
                item["expected_pct"] = elapsed_pct
                pacing_fast.append(item)
            else:
                item["status"] = "on_track"
                on_track.append(item)

        total_remaining = round(total_budgeted - total_actual, 2)
        overall_spent_pct = round((total_actual / total_budgeted * 100.0), 1) if total_budgeted > 0 else 0.0

        return {
            "month": month_str,
            "days_elapsed": day_of_month,
            "days_in_month": days_in_month,
            "days_remaining": days_left,
            "elapsed_pct": elapsed_pct,
            "totals": {
                "budgeted": round(total_budgeted, 2),
                "actual": round(total_actual, 2),
                "remaining": total_remaining,
                "spent_pct": overall_spent_pct,
            },
            "categories": {
                "over_budget": over_budget,
                "pacing_fast": pacing_fast,
                "on_track": on_track,
            },
        }
