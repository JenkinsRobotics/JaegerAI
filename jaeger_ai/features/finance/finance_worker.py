"""Autonomous finance worker for JaegerAI.

Performs continuous budget pacing calculations, anomaly detection (spikes,
duplicate charges), and generates actionable executive briefings for chat and Siri.

Reports are written only under ``~/.jaeger/reports/finance/`` (or
``$JAEGER_STATE_DIR/reports/finance/``).
"""

from __future__ import annotations

import calendar
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .monarch_service import MonarchError, MonarchService, MonarchSessionMissing

logger = logging.getLogger("jaeger_ai.features.finance.worker")

MAX_CATEGORIES = 200
MAX_TRANSACTIONS = 500
LARGE_TX_THRESHOLD = 150.0


def _reports_dir() -> Path:
    raw = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME")
    root = Path(raw).expanduser().resolve() if raw else (Path.home() / ".jaeger").resolve()
    path = root / "reports" / "finance"
    path.mkdir(parents=True, exist_ok=True)
    return path


class FinanceWorker:
    """Autonomous financial auditor and budget pacing engine."""

    def __init__(self, service: MonarchService | None = None) -> None:
        self.service = service or MonarchService()

    def _persist_report(self, payload: dict[str, Any]) -> Path | None:
        """Write audit JSON only under ~/.jaeger/reports/finance/."""
        try:
            reports = _reports_dir()
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            latest = reports / "latest.json"
            stamped = reports / f"audit-{stamp}.json"
            body = json.dumps(payload, indent=2, default=str)
            latest.write_text(body, encoding="utf-8")
            stamped.write_text(body, encoding="utf-8")
            # Cap retained stamped reports (no unbounded growth)
            stamped_files = sorted(reports.glob("audit-*.json"), key=lambda p: p.name)
            for old in stamped_files[:-20]:
                try:
                    old.unlink()
                except OSError:
                    pass
            return latest
        except OSError as exc:
            logger.warning("Failed to persist finance report: %s", type(exc).__name__)
            return None

    async def audit(self, days: int = 7) -> dict[str, Any]:
        """Perform a complete financial health, budget pacing, and transaction audit."""
        days = max(1, min(int(days), 90))

        if not self.service.is_session_available():
            return {
                "ok": False,
                "error": "Monarch Money session missing; connect before auditing.",
            }

        try:
            accounts_res = await self.service.get_accounts()
            budgets_res = await self.service.get_budgets()
            tx_res = await self.service.get_recent_transactions(days=days)
        except MonarchSessionMissing as exc:
            return {"ok": False, "error": str(exc)}
        except MonarchError as exc:
            logger.warning("Finance audit API error: %s", type(exc).__name__)
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Finance audit unexpected error: %s", type(exc).__name__)
            return {"ok": False, "error": f"Finance audit failed: {type(exc).__name__}"}

        if not accounts_res.get("ok"):
            return {
                "ok": False,
                "error": accounts_res.get("error", "Unable to retrieve account balances."),
            }

        # Soft-fail budgets/tx: still produce account briefing if they error
        if not budgets_res.get("ok"):
            logger.warning("Budget fetch failed during audit: %s", budgets_res.get("error"))
            budgets_res = {"ok": False, "categories": []}
        if not tx_res.get("ok"):
            logger.warning("Transaction fetch failed during audit: %s", tx_res.get("error"))
            tx_res = {"ok": False, "transactions": []}

        now = datetime.now(UTC)
        _, days_in_month = calendar.monthrange(now.year, now.month)
        elapsed_ratio = min(1.0, max(0.0, now.day / float(days_in_month)))
        elapsed_pct = round(elapsed_ratio * 100, 1)

        categories = list(budgets_res.get("categories", []) or [])[:MAX_CATEGORIES]
        pacing_alerts: list[dict[str, Any]] = []
        over_budget: list[dict[str, Any]] = []
        healthy_categories: list[dict[str, Any]] = []

        for c in categories:
            budgeted = float(c.get("budgeted", 0.0) or 0.0)
            actual = float(c.get("actual", 0.0) or 0.0)
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

        transactions = list(tx_res.get("transactions", []) or [])[:MAX_TRANSACTIONS]
        large_transactions: list[dict[str, Any]] = []
        uncategorized: list[dict[str, Any]] = []
        seen_charges: dict[str, list[dict[str, Any]]] = {}
        duplicates: list[dict[str, Any]] = []

        for tx in transactions:
            amt = abs(float(tx.get("amount", 0.0) or 0.0))
            merchant = str(tx.get("merchant", "Unknown") or "Unknown")
            cat = str(tx.get("category", "") or "")

            if amt >= LARGE_TX_THRESHOLD:
                large_transactions.append(tx)

            if not cat or cat.lower() in {"uncategorized", "unknown", "needs review"}:
                uncategorized.append(tx)

            key = f"{merchant.lower()}:{amt:.2f}"
            if key in seen_charges:
                duplicates.append({"original": seen_charges[key][0], "duplicate": tx})
            else:
                seen_charges[key] = [tx]

        summary_markdown = self._format_briefing(
            accounts=accounts_res,
            elapsed_pct=elapsed_pct,
            over_budget=over_budget,
            pacing_alerts=pacing_alerts,
            large_transactions=large_transactions,
            duplicates=duplicates,
            uncategorized=uncategorized,
        )

        result: dict[str, Any] = {
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

        report_path = self._persist_report({
            "ok": True,
            "timestamp": result["timestamp"],
            "accounts_summary": result["accounts_summary"],
            "pacing": result["pacing"],
            "anomalies": {
                "large_count": len(large_transactions),
                "duplicate_count": len(duplicates),
                "uncategorized_count": len(uncategorized),
            },
            "briefing": summary_markdown,
        })
        if report_path is not None:
            result["report_path"] = str(report_path)

        return result

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
            for c in over_budget[:20]:
                lines.append(
                    f"- **{c['category']}**: Spent ${c['actual']:,.2f} of "
                    f"${c['budgeted']:,.2f} (+${c['over_by']:,.2f} over limit)"
                )
            lines.append("")

        if pacing_alerts:
            lines.append("⚠️ **Pacing Fast (Exceeding Expected Run Rate):**")
            for c in pacing_alerts[:20]:
                lines.append(
                    f"- **{c['category']}**: {c['spent_pct']}% spent "
                    f"(${c['actual']:,.2f}/${c['budgeted']:,.2f}, remaining: ${c['remaining']:,.2f})"
                )
            lines.append("")

        if duplicates:
            lines.append("⚠️ **Potential Duplicate Charges Detected:**")
            for d in duplicates[:10]:
                tx = d["duplicate"]
                lines.append(f"- ${tx['amount']:,.2f} at {tx['merchant']} on {tx['date']}")
            lines.append("")

        if large_transactions:
            lines.append("🔍 **Notable Recent Charges (Past 7 Days):**")
            for tx in large_transactions[:5]:
                lines.append(
                    f"- ${tx['amount']:,.2f} at {tx['merchant']} ({tx['category']}) on {tx['date']}"
                )
            lines.append("")

        if uncategorized:
            lines.append(f"📥 **Needs Categorization ({len(uncategorized)} charges):**")
            for tx in uncategorized[:4]:
                lines.append(f"- ${tx['amount']:,.2f} at {tx['merchant']} on {tx['date']}")
            lines.append("")

        if not over_budget and not pacing_alerts and not duplicates:
            lines.append(
                "✅ **All budget categories are pacing normally within expected monthly burn rate.**"
            )

        return "\n".join(lines)
