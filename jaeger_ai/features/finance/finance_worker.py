"""Autonomous finance worker for JaegerAI.

Performs continuous budget pacing calculations, anomaly detection (spikes,
duplicate charges), and generates actionable executive briefings for chat and Siri.
"""

from __future__ import annotations

import calendar
import logging
from datetime import UTC, datetime
from typing import Any

from .monarch_service import MonarchService

logger = logging.getLogger("jaeger_ai.features.finance.worker")


class FinanceWorker:
    """Autonomous financial auditor and budget pacing engine."""

    def __init__(self, service: MonarchService | None = None) -> None:
        self.service = service or MonarchService()

    async def audit(self, days: int = 7) -> dict[str, Any]:
        """Perform a complete financial health, budget pacing, and transaction audit."""
        accounts_res = await self.service.get_accounts()
        budgets_res = await self.service.get_budgets()
        tx_res = await self.service.get_recent_transactions(days=days)

        if not accounts_res.get("ok"):
            return {
                "ok": False,
                "error": accounts_res.get("error", "Unable to retrieve account balances."),
            }

        now = datetime.now(UTC)
        _, days_in_month = calendar.monthrange(now.year, now.month)
        elapsed_ratio = min(1.0, max(0.0, now.day / float(days_in_month)))
        elapsed_pct = round(elapsed_ratio * 100, 1)

        # 1. Budget Pacing Analysis
        categories = budgets_res.get("categories", [])
        pacing_alerts = []
        over_budget = []
        healthy_categories = []

        for c in categories:
            budgeted = c.get("budgeted", 0.0)
            actual = c.get("actual", 0.0)
            if budgeted <= 0:
                continue

            spent_ratio = actual / budgeted
            spent_pct = round(spent_ratio * 100, 1)

            if actual > budgeted:
                over_budget.append({
                    "category": c["category"],
                    "budgeted": budgeted,
                    "actual": actual,
                    "over_by": round(actual - budgeted, 2),
                    "spent_pct": spent_pct,
                })
            elif spent_ratio > (elapsed_ratio + 0.15):
                pacing_alerts.append({
                    "category": c["category"],
                    "budgeted": budgeted,
                    "actual": actual,
                    "remaining": c.get("remaining", 0.0),
                    "spent_pct": spent_pct,
                    "expected_pct": elapsed_pct,
                })
            else:
                healthy_categories.append(c)

        # 2. Transaction Anomalies & Review Queue
        transactions = tx_res.get("transactions", [])
        large_transactions = []
        uncategorized = []
        seen_charges: dict[str, list[dict[str, Any]]] = {}
        duplicates = []

        for tx in transactions:
            amt = abs(tx.get("amount", 0.0))
            merchant = tx.get("merchant", "Unknown")
            cat = tx.get("category", "")

            # Flag large single purchases (>$150)
            if amt >= 150.0:
                large_transactions.append(tx)

            # Uncategorized check
            if not cat or cat.lower() in {"uncategorized", "unknown", "needs review"}:
                uncategorized.append(tx)

            # Duplicate charge detection (same merchant & amount within 48h)
            key = f"{merchant.lower()}:{amt:.2f}"
            if key in seen_charges:
                duplicates.append({"original": seen_charges[key][0], "duplicate": tx})
            else:
                seen_charges[key] = [tx]

        # 3. Assemble Executive Briefing
        summary_markdown = self._format_briefing(
            accounts=accounts_res,
            elapsed_pct=elapsed_pct,
            over_budget=over_budget,
            pacing_alerts=pacing_alerts,
            large_transactions=large_transactions,
            duplicates=duplicates,
            uncategorized=uncategorized,
        )

        return {
            "ok": True,
            "timestamp": now.isoformat(),
            "month_elapsed_pct": elapsed_pct,
            "accounts_summary": {
                "net_worth": accounts_res.get("net_worth", 0.0),
                "liquid_cash": accounts_res.get("liquid_cash", 0.0),
                "credit_debt": accounts_res.get("credit_debt", 0.0),
            },
            "pacing": {
                "over_budget": over_budget,
                "pacing_fast": pacing_alerts,
                "healthy_count": len(healthy_categories),
            },
            "anomalies": {
                "large_transactions": large_transactions,
                "duplicates": duplicates,
                "uncategorized": uncategorized,
            },
            "briefing": summary_markdown,
        }

    def _format_briefing(
        self,
        accounts: dict[str, Any],
        elapsed_pct: float,
        over_budget: list[dict[str, Any]],
        pacing_alerts: list[dict[str, Any]],
        large_transactions: list[dict[str, Any]],
        duplicates: list[dict[str, Any]],
        uncategorized: list[dict[str, Any]],
    ) -> str:
        """Format a human-readable executive briefing markdown."""
        lines = [
            "### 💳 Financial Health & Budget Briefing",
            (
                f"**Net Worth:** ${accounts.get('net_worth', 0.0):,.2f} | "
                f"**Liquid Cash:** ${accounts.get('liquid_cash', 0.0):,.2f} | "
                f"**Credit Debt:** ${accounts.get('credit_debt', 0.0):,.2f}"
            ),
            f"*Month Progress:* {elapsed_pct}% elapsed.",
            "",
        ]

        if over_budget:
            lines.append("🚨 **Over Budget Categories:**")
            for c in over_budget:
                lines.append(f"- **{c['category']}**: Spent ${c['actual']:,.2f} of ${c['budgeted']:,.2f} (+${c['over_by']:,.2f} over limit)")
            lines.append("")

        if pacing_alerts:
            lines.append("⚠️ **Pacing Fast (Exceeding Expected Run Rate):**")
            for c in pacing_alerts:
                lines.append(f"- **{c['category']}**: {c['spent_pct']}% spent (${c['actual']:,.2f}/${c['budgeted']:,.2f}, remaining: ${c['remaining']:,.2f})")
            lines.append("")

        if duplicates:
            lines.append("⚠️ **Potential Duplicate Charges Detected:**")
            for d in duplicates:
                tx = d["duplicate"]
                lines.append(f"- ${tx['amount']:,.2f} at {tx['merchant']} on {tx['date']}")
            lines.append("")

        if large_transactions:
            lines.append("🔍 **Notable Recent Charges (Past 7 Days):**")
            for tx in large_transactions[:5]:
                lines.append(f"- ${tx['amount']:,.2f} at {tx['merchant']} ({tx['category']}) on {tx['date']}")
            lines.append("")

        if uncategorized:
            lines.append(f"📥 **Needs Categorization ({len(uncategorized)} charges):**")
            for tx in uncategorized[:4]:
                lines.append(f"- ${tx['amount']:,.2f} at {tx['merchant']} on {tx['date']}")
            lines.append("")

        if not over_budget and not pacing_alerts and not duplicates:
            lines.append("✅ **All budget categories are pacing normally within expected monthly burn rate.**")

        return "\n".join(lines)
