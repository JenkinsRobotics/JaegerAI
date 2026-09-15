"""Daily, weekly, and monthly financial briefing generation engine."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .anomaly import AnomalyDetector
from .budget import BudgetEngine
from .cashflow import CashFlowEngine
from .classifier import TransactionClassifier
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.briefing")


class BriefingEngine:
    """Produces objective, proactive, privacy-conscious financial executive briefings."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store
        self.budget_engine = BudgetEngine(store)
        self.cashflow_engine = CashFlowEngine(store)
        self.anomaly_detector = AnomalyDetector(store)
        self.classifier = TransactionClassifier(store)

    def generate_daily_briefing(self) -> dict[str, Any]:
        """Produce a concise morning briefing focused on immediate actions and runways."""
        runway = self.cashflow_engine.calculate_runway()
        anomalies = self.anomaly_detector.detect_anomalies(days=7)
        inbox = self.classifier.get_inbox_items()
        pacing = self.budget_engine.evaluate_pacing()

        lines = [
            "### ☀️ Daily Financial Briefing",
            f"**Liquid Checking:** ${runway['liquid_checking']:,.2f} | "
            f"**Runway:** ~{runway['checking_runway_days']} days | "
            f"**Net Worth:** ${runway['net_worth']:,.2f}",
            "",
        ]

        if runway.get("shortfall_warning"):
            lines.append(f"⚠️ **Cash Flow Notice:** {runway['shortfall_warning']}\n")

        if inbox:
            lines.append(f"📥 **Review Inbox ({len(inbox)} items require attention):**")
            for item in inbox[:3]:
                tx = item["transaction"]
                lines.append(f"- ${tx['amount']:,.2f} at **{tx['merchant']}** on {tx['date']} ({', '.join(item['reasons'])})")
            if len(inbox) > 3:
                lines.append(f"*+{len(inbox) - 3} more in inbox. Use `/finance inbox` to review.*")
            lines.append("")

        if anomalies["duplicates"]:
            lines.append("⚠️ **Potential Duplicate Charges:**")
            for dup in anomalies["duplicates"][:2]:
                lines.append(f"- ${dup['amount']:,.2f} at **{dup['merchant']}** ({dup['date1']} vs {dup['date2']})")
            lines.append("")

        # Notable category pacing alerts
        fast = pacing["categories"]["pacing_fast"]
        if fast:
            top_fast = fast[0]
            lines.append(
                f"📊 **Pacing Note:** {top_fast['category']} is currently pacing at {top_fast['spent_pct']}% of budget "
                f"(${top_fast['actual']:,.2f}/${top_fast['budgeted']:,.2f}). Remaining daily allowance: "
                f"${top_fast['daily_allowance_remaining']:,.2f}/day."
            )

        markdown = "\n".join(lines)
        return {
            "type": "daily",
            "timestamp": datetime.now(UTC).isoformat(),
            "markdown": markdown,
            "runway": runway,
            "inbox_count": len(inbox),
            "duplicate_count": len(anomalies["duplicates"]),
        }

    def generate_weekly_briefing(self) -> dict[str, Any]:
        """Produce a comprehensive weekly summary of budget pacing, cash flow, and subscriptions."""
        runway = self.cashflow_engine.calculate_runway()
        pacing = self.budget_engine.evaluate_pacing()
        anomalies = self.anomaly_detector.detect_anomalies(days=14)
        inbox = self.classifier.get_inbox_items()

        lines = [
            "### 💳 Weekly Household Finance Summary",
            (
                f"**Net Worth:** ${runway['net_worth']:,.2f} | "
                f"**Liquid Cash:** ${runway['total_liquid']:,.2f} | "
                f"**Credit Debt:** ${runway['credit_card_debt']:,.2f}"
            ),
            f"*Month Progress:* {pacing['elapsed_pct']}% elapsed ({pacing['days_remaining']} days remaining in {pacing['month']}).",
            "",
        ]

        if runway.get("shortfall_warning"):
            lines.append(f"⚠️ **Cash Flow Advisory:** {runway['shortfall_warning']}\n")

        # Category status
        over_budget = pacing["categories"]["over_budget"]
        pacing_fast = pacing["categories"]["pacing_fast"]

        if over_budget:
            lines.append("🚨 **Over Budget Categories:**")
            for c in over_budget:
                lines.append(
                    f"- **{c['category']}**: Spent ${c['actual']:,.2f} of ${c['budgeted']:,.2f} "
                    f"(+${c['over_by']:,.2f} over limit)"
                )
            lines.append("")

        if pacing_fast:
            lines.append("⚠️ **Pacing Ahead of Schedule:**")
            for c in pacing_fast[:5]:
                lines.append(
                    f"- **{c['category']}**: {c['spent_pct']}% spent (${c['actual']:,.2f}/${c['budgeted']:,.2f}). "
                    f"You have ${c['remaining']:,.2f} remaining for the next {pacing['days_remaining']} days "
                    f"(${c['daily_allowance_remaining']:,.2f}/day). "
                    f"At current pace, projected total spend is ${c['projected_spend']:,.2f}."
                )
            lines.append("")

        if anomalies["subscription_hikes"]:
            lines.append("📈 **Subscription Price Increases Detected:**")
            for sub in anomalies["subscription_hikes"]:
                lines.append(f"- **{sub['merchant']}**: Increased from ${sub['prior_amount']:,.2f} to ${sub['current_amount']:,.2f} (+${sub['increase']:,.2f})")
            lines.append("")

        if anomalies["duplicates"]:
            lines.append("🔍 **Duplicate Alerts:**")
            for d in anomalies["duplicates"][:3]:
                lines.append(f"- ${d['amount']:,.2f} at {d['merchant']} on {d['date1']} and {d['date2']}")
            lines.append("")

        if inbox:
            lines.append(f"📥 **{len(inbox)} Transactions awaiting review in Inbox.**")
            lines.append("")

        if not over_budget and not pacing_fast:
            lines.append("✅ **All budget categories are pacing comfortably within monthly envelopes.**")

        markdown = "\n".join(lines)
        return {
            "type": "weekly",
            "timestamp": datetime.now(UTC).isoformat(),
            "markdown": markdown,
            "totals": pacing["totals"],
            "pacing": pacing["categories"],
            "runway": runway,
            "anomalies": anomalies,
        }

    def generate_monthly_close(self, month: str | None = None) -> dict[str, Any]:
        """Produce an end-of-month reconciliation and budget variance review."""
        now = datetime.now(UTC)
        month_str = month or now.strftime("%Y-%m")
        pacing = self.budget_engine.evaluate_pacing(month=month_str)
        runway = self.cashflow_engine.calculate_runway()
        anomalies = self.anomaly_detector.detect_anomalies(days=31)

        lines = [
            f"### 📑 Monthly Financial Close — {month_str}",
            f"**Total Budgeted:** ${pacing['totals']['budgeted']:,.2f} | "
            f"**Actual Spent:** ${pacing['totals']['actual']:,.2f} | "
            f"**Variance:** ${pacing['totals']['remaining']:,.2f}",
            "",
            "#### Budget Variance Breakdown:",
        ]

        for c in pacing["categories"]["over_budget"]:
            lines.append(f"- 🔴 **{c['category']}**: Over by ${c['over_by']:,.2f} (${c['actual']:,.2f} spent vs ${c['budgeted']:,.2f})")
        for c in pacing["categories"]["on_track"]:
            lines.append(f"- 🟢 **{c['category']}**: Under by ${c['remaining']:,.2f} (${c['actual']:,.2f} spent of ${c['budgeted']:,.2f})")

        lines.extend([
            "",
            "#### Reconciliation & Health:",
            f"- **Uncategorized Charges:** {anomalies['uncategorized_count']}",
            f"- **Identified Duplicates:** {anomalies['duplicate_count']}",
            f"- **Ending Net Worth:** ${runway['net_worth']:,.2f}",
            "",
            "*Phase 1 Protection: Proposed budget updates for next month require operator review before any mutation.*",
        ])

        markdown = "\n".join(lines)
        return {
            "type": "monthly_close",
            "month": month_str,
            "timestamp": now.isoformat(),
            "markdown": markdown,
            "totals": pacing["totals"],
            "variances": pacing["categories"],
        }
