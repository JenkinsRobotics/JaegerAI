"""Monarch Money adapter implementing FinanceProvider (Strictly Read-Only in Phase 1)."""

from __future__ import annotations

import logging
from typing import Any

from ..models import Account, AccountType, Category, CategoryBudget, Transaction
from ..monarch_service import MonarchError, MonarchService
from ..security import SecuritySanitizer

logger = logging.getLogger("jaeger_ai.features.finance.providers.monarch")


class MonarchProvider:
    """Read-only Monarch Money provider."""

    def __init__(self, service: MonarchService | None = None) -> None:
        self.service = service or MonarchService()

    @property
    def provider_name(self) -> str:
        return "monarch"

    def is_available(self) -> bool:
        return self.service.is_session_available()

    async def get_accounts(self) -> list[Account]:
        raw_res = await self.service.get_accounts()
        if not raw_res.get("ok"):
            logger.warning("Monarch get_accounts failed: %s", raw_res.get("error"))
            return []

        accounts: list[Account] = []
        for raw in raw_res.get("accounts", []):
            mask = SecuritySanitizer.mask_account_identifier(raw.get("mask") or raw.get("id"))
            accounts.append(
                Account(
                    id=str(raw.get("id") or ""),
                    name=str(raw.get("name") or "Unnamed Account"),
                    type=AccountType.from_str(raw.get("type")),
                    balance=float(raw.get("balance") or 0.0),
                    currency="USD",
                    mask=mask,
                    subtype=str(raw.get("type") or ""),
                    is_hidden=bool(raw.get("is_hidden", False)),
                    updated_at=raw.get("updated_at"),
                    provider="monarch",
                )
            )
        return accounts

    async def get_transactions(
        self,
        start_date: str,
        end_date: str,
        limit: int = 500,
    ) -> list[Transaction]:
        raw_res = await self.service.get_recent_transactions(
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )
        if not raw_res.get("ok"):
            logger.warning("Monarch get_transactions failed: %s", raw_res.get("error"))
            return []

        transactions: list[Transaction] = []
        for raw in raw_res.get("transactions", []):
            tags = raw.get("tags") or []
            if isinstance(tags, list):
                tag_names = [t.get("name") if isinstance(t, dict) else str(t) for t in tags]
            else:
                tag_names = []

            tx_id = str(raw.get("id") or "")
            account_id = str(raw.get("accountId") or raw.get("account_id") or "monarch_acct")
            merchant = str(raw.get("merchant") or raw.get("plaidName") or "Unknown Merchant")
            stmt = str(raw.get("originalStatementName") or raw.get("statement") or merchant)

            transactions.append(
                Transaction(
                    id=tx_id,
                    account_id=account_id,
                    account_name=str(raw.get("account") or ""),
                    date=str(raw.get("date") or ""),
                    amount=float(raw.get("amount") or 0.0),
                    merchant=merchant,
                    raw_statement=stmt,
                    category=str(raw.get("category") or "Uncategorized"),
                    category_id=raw.get("categoryId"),
                    pending=bool(raw.get("pending", False)),
                    is_split=bool(raw.get("isSplit") or raw.get("is_split", False)),
                    parent_id=raw.get("parentTransactionId") or raw.get("parent_id"),
                    notes=str(raw.get("notes") or ""),
                    tags=tag_names,
                    provider="monarch",
                )
            )
        return transactions

    async def get_budgets(self, month: str | None = None) -> list[CategoryBudget]:
        raw_res = await self.service.get_budgets()
        if not raw_res.get("ok"):
            logger.warning("Monarch get_budgets failed: %s", raw_res.get("error"))
            return []

        budgets: list[CategoryBudget] = []
        for raw in raw_res.get("categories", []):
            cat_name = str(raw.get("category") or "General")
            budgeted = float(raw.get("budgeted") or 0.0)
            actual = float(raw.get("actual") or 0.0)
            remaining = float(raw.get("remaining") or (budgeted - actual))
            spent_pct = (actual / budgeted * 100.0) if budgeted > 0 else 0.0

            budgets.append(
                CategoryBudget(
                    category=cat_name,
                    budgeted=budgeted,
                    actual=actual,
                    remaining=remaining,
                    spent_pct=spent_pct,
                )
            )
        return budgets

    async def get_categories(self) -> list[Category]:
        # Fetch categories if client available, otherwise empty
        if not self.is_available():
            return []
        try:
            client = self.service._get_client()
            raw = await self.service._call(client.get_transaction_categories(), op="get_categories")
            cats = raw.get("categories", []) if isinstance(raw, dict) else []
            out: list[Category] = []
            for c in cats:
                out.append(
                    Category(
                        id=str(c.get("id") or ""),
                        name=str(c.get("name") or "Category"),
                        group_name=str(c.get("group", {}).get("name") or "General"),
                        is_income=bool(c.get("isIncome", False)),
                        is_system=bool(c.get("isSystem", False)),
                    )
                )
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch Monarch categories: %s", type(exc).__name__)
            return []
