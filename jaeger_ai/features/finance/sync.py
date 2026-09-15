"""Idempotent synchronization engine coordinating providers and encrypted local store."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import SyncSummary
from .provider import FinanceProvider
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.sync")

DEFAULT_SYNC_DAYS = 30
MAX_SYNC_RETRIES = 3


class SyncEngine:
    """Manages idempotent pull from finance providers into FinanceStore."""

    def __init__(self, store: FinanceStore, provider: FinanceProvider) -> None:
        self.store = store
        self.provider = provider

    async def sync(
        self,
        days: int = DEFAULT_SYNC_DAYS,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> SyncSummary:
        """Run idempotent synchronization for accounts, transactions, and budgets."""
        p_name = self.provider.provider_name
        if not self.provider.is_available():
            err_msg = f"Provider {p_name} is unavailable or unauthenticated."
            self.store.update_sync_state(p_name, "error", {"error": err_msg})
            return SyncSummary(ok=False, provider=p_name, error=err_msg)

        now = datetime.now(UTC)
        if not start_date or not end_date:
            end_date = now.strftime("%Y-%m-%d")
            start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        month_str = now.strftime("%Y-%m")
        attempts = 0
        last_error: Exception | None = None

        while attempts < MAX_SYNC_RETRIES:
            attempts += 1
            try:
                # 1. Accounts
                accounts = await self.provider.get_accounts()
                accts_synced = self.store.upsert_accounts(accounts)

                # 2. Transactions
                transactions = await self.provider.get_transactions(
                    start_date=start_date,
                    end_date=end_date,
                    limit=500,
                )
                tx_inserted, tx_skipped = self.store.upsert_transactions(transactions)

                # 3. Budgets
                budgets = await self.provider.get_budgets(month=month_str)
                budgets_synced = self.store.upsert_budgets(budgets, month=month_str)

                summary = SyncSummary(
                    ok=True,
                    provider=p_name,
                    accounts_synced=accts_synced,
                    transactions_synced=tx_inserted,
                    duplicates_skipped=tx_skipped,
                    budgets_synced=budgets_synced,
                    synced_at=now.isoformat(),
                )

                # Update sync state & audit log
                self.store.update_sync_state(p_name, "success", summary.to_dict())
                self.store.append_audit("sync_complete", f"provider:{p_name}", summary.to_dict())
                return summary

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Sync attempt %d/%d for %s failed: %s",
                    attempts,
                    MAX_SYNC_RETRIES,
                    p_name,
                    type(exc).__name__,
                )
                if attempts < MAX_SYNC_RETRIES:
                    await asyncio.sleep(0.5 * (2 ** (attempts - 1)))

        err_text = f"Sync failed after {MAX_SYNC_RETRIES} attempts: {type(last_error).__name__}"
        self.store.update_sync_state(p_name, "failed", {"error": err_text})
        self.store.append_audit("sync_failed", f"provider:{p_name}", {"error": err_text})
        return SyncSummary(ok=False, provider=p_name, error=err_text)
