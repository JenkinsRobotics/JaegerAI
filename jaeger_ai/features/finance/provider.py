"""Normalized provider interface for personal finance data sources."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Account, Category, CategoryBudget, Transaction


@runtime_checkable
class FinanceProvider(Protocol):
    """Normalized protocol implemented by all financial adapters (Monarch, CSV, mock)."""

    @property
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'monarch', 'csv_import', 'synthetic')."""
        ...

    def is_available(self) -> bool:
        """Return True if the provider is configured and reachable."""
        ...

    async def get_accounts(self) -> list[Account]:
        """Fetch normalized accounts and balances."""
        ...

    async def get_transactions(
        self,
        start_date: str,
        end_date: str,
        limit: int = 500,
    ) -> list[Transaction]:
        """Fetch transactions within an inclusive date range (YYYY-MM-DD)."""
        ...

    async def get_budgets(self, month: str | None = None) -> list[CategoryBudget]:
        """Fetch monthly category budget allocations and spend totals."""
        ...

    async def get_categories(self) -> list[Category]:
        """Fetch all known category definitions."""
        ...
