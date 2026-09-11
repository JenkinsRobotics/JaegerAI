"""Monarch Money service wrapper for JaegerAI.

Provides reliable session loading from ~/.ares/.mm_session.pickle, account balance
aggregation, transaction fetching, and monthly budget pacing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("jaeger_ai.features.finance.monarch")

DEFAULT_SESSION_PATH = Path.home() / ".ares/.mm_session.pickle"


class MonarchService:
    """Service wrapping Monarch Money GraphQL API."""

    def __init__(self, session_path: Path | None = None) -> None:
        self.session_path = session_path or DEFAULT_SESSION_PATH
        self._mm: Any = None

    def is_session_available(self) -> bool:
        """Check if the session pickle file exists and is non-empty."""
        return self.session_path.is_file() and self.session_path.stat().st_size > 0

    def _get_client(self) -> Any:
        """Instantiate MonarchMoney client and load saved session."""
        if self._mm is not None:
            return self._mm

        if not self.is_session_available():
            raise FileNotFoundError(
                f"Monarch Money session not found at {self.session_path}. "
                "Please connect your account via the Monarch sheet or login command."
            )

        try:
            from monarchmoney import MonarchMoney
        except ImportError as exc:
            raise ImportError(
                "monarchmoney package is not installed. Install via `uv pip install monarchmoney 'gql<4'`."
            ) from exc

        mm = MonarchMoney(session_file=str(self.session_path))
        mm.load_session(str(self.session_path))
        self._mm = mm
        return self._mm

    async def get_accounts(self) -> dict[str, Any]:
        """Fetch all connected financial accounts and calculate aggregate balances."""
        client = self._get_client()
        try:
            raw = await client.get_accounts()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch Monarch accounts: %s", exc)
            return {"ok": False, "error": str(exc), "accounts": []}

        accounts_list: list[dict[str, Any]] = raw.get("accounts", []) if isinstance(raw, dict) else raw

        liquid_cash = 0.0
        credit_debt = 0.0
        loan_debt = 0.0
        investments = 0.0
        parsed_accounts = []

        for acct in accounts_list:
            name = acct.get("displayName") or acct.get("name") or "Unnamed Account"
            balance = float(acct.get("currentBalance") or 0.0)
            raw_type = acct.get("type", {})
            type_name = (raw_type.get("name") if isinstance(raw_type, dict) else str(raw_type or "")).lower()

            parsed_accounts.append({
                "id": acct.get("id"),
                "name": name,
                "type": type_name,
                "balance": balance,
                "updated_at": acct.get("updatedAt"),
                "is_hidden": acct.get("isHidden", False),
            })

            if "depository" in type_name or "checking" in type_name or "savings" in type_name:
                liquid_cash += balance
            elif "credit" in type_name:
                credit_debt += abs(balance)
            elif "loan" in type_name or "mortgage" in type_name:
                loan_debt += abs(balance)
            elif "investment" in type_name or "brokerage" in type_name:
                investments += balance

        net_worth = (liquid_cash + investments) - (credit_debt + loan_debt)

        return {
            "ok": True,
            "account_count": len(parsed_accounts),
            "liquid_cash": round(liquid_cash, 2),
            "investments": round(investments, 2),
            "credit_debt": round(credit_debt, 2),
            "loan_debt": round(loan_debt, 2),
            "net_worth": round(net_worth, 2),
            "accounts": parsed_accounts,
        }

    async def get_recent_transactions(self, days: int = 7, limit: int = 100) -> dict[str, Any]:
        """Fetch transactions from the past N days."""
        client = self._get_client()
        now = datetime.now(UTC)
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        try:
            raw = await client.get_transactions(limit=limit, start_date=start_date, end_date=end_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch Monarch transactions: %s", exc)
            return {"ok": False, "error": str(exc), "transactions": []}

        tx_list = raw.get("allTransactions", {}).get("results", []) if isinstance(raw, dict) else raw
        parsed = []
        for tx in tx_list:
            category = tx.get("category") or {}
            cat_name = category.get("name") if isinstance(category, dict) else str(category or "Uncategorized")
            merchant = tx.get("merchant") or {}
            merchant_name = merchant.get("name") if isinstance(merchant, dict) else tx.get("plaidName") or "Unknown"

            parsed.append({
                "id": tx.get("id"),
                "date": tx.get("date"),
                "amount": float(tx.get("amount") or 0.0),
                "merchant": merchant_name,
                "category": cat_name,
                "pending": tx.get("pending", False),
                "account": (tx.get("account") or {}).get("displayName", "Account"),
            })

        return {
            "ok": True,
            "count": len(parsed),
            "since": start_date,
            "until": end_date,
            "transactions": parsed,
        }

    async def get_budgets(self) -> dict[str, Any]:
        """Fetch current month budget targets and actual spending."""
        client = self._get_client()
        now = datetime.now(UTC)
        start_date = now.strftime("%Y-%m-01")
        import calendar
        _, days_in_month = calendar.monthrange(now.year, now.month)
        end_date = now.strftime(f"%Y-%m-{days_in_month:02d}")

        try:
            raw = await client.get_budgets(start_date=start_date, end_date=end_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch Monarch budgets: %s", exc)
            return {"ok": False, "error": str(exc), "categories": []}

        category_budgets = []
        raw_cats = raw.get("budgetData", {}).get("categories", []) if isinstance(raw, dict) else []

        for c in raw_cats:
            cat_obj = c.get("category", {})
            name = cat_obj.get("name", "Category")
            budgeted = float(c.get("budgetedAmount") or 0.0)
            actual = float(c.get("actualAmount") or 0.0)
            category_budgets.append({
                "category": name,
                "budgeted": budgeted,
                "actual": actual,
                "remaining": round(budgeted - actual, 2),
            })

        return {
            "ok": True,
            "month": now.strftime("%B %Y"),
            "categories": category_budgets,
        }

    def get_accounts_sync(self) -> dict[str, Any]:
        """Synchronous wrapper for get_accounts."""
        return asyncio.run(self.get_accounts())

    def get_recent_transactions_sync(self, days: int = 7, limit: int = 100) -> dict[str, Any]:
        """Synchronous wrapper for get_recent_transactions."""
        return asyncio.run(self.get_recent_transactions(days=days, limit=limit))

    def get_budgets_sync(self) -> dict[str, Any]:
        """Synchronous wrapper for get_budgets."""
        return asyncio.run(self.get_budgets())
