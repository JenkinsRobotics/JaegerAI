"""CSV and JSON Import provider for offline synchronization, data migrations, and test fixtures."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..models import Account, AccountType, Category, CategoryBudget, Transaction
from ..security import SecuritySanitizer

logger = logging.getLogger("jaeger_ai.features.finance.providers.importer")


class ImportProvider:
    """Provider for importing transactions, accounts, and budgets from CSV or JSON."""

    def __init__(
        self,
        csv_path: Path | str | None = None,
        json_path: Path | str | None = None,
        accounts: list[Account] | None = None,
        transactions: list[Transaction] | None = None,
        budgets: list[CategoryBudget] | None = None,
    ) -> None:
        self.csv_path = Path(csv_path) if csv_path else None
        self.json_path = Path(json_path) if json_path else None
        self._accounts: list[Account] = list(accounts or [])
        self._transactions: list[Transaction] = list(transactions or [])
        self._budgets: list[CategoryBudget] = list(budgets or [])

        if self.json_path and self.json_path.is_file():
            self._load_json(self.json_path)
        elif self.csv_path and self.csv_path.is_file():
            self._load_csv(self.csv_path)

    @property
    def provider_name(self) -> str:
        return "import_csv_json"

    def is_available(self) -> bool:
        return bool(self._transactions or self._accounts or (self.csv_path and self.csv_path.is_file()))

    def _parse_amount(self, val: Any) -> float:
        if isinstance(val, (int, float)):
            return float(val)
        raw = str(val or "0.0").replace("$", "").replace(",", "").strip()
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def _normalize_date(self, val: str) -> str:
        raw = val.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return raw

    def _load_csv(self, path: Path) -> None:
        content = path.read_text(encoding="utf-8", errors="replace")
        self.load_csv_data(content)

    def load_csv_data(self, csv_text: str) -> None:
        reader = csv.DictReader(io.StringIO(csv_text))
        inferred_accounts: dict[str, Account] = {}

        for row in reader:
            # Match Monarch CSV columns or generic columns (case-insensitive)
            normalized_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            date_raw = normalized_row.get("date") or datetime.now(UTC).strftime("%Y-%m-%d")
            date_iso = self._normalize_date(date_raw)

            merchant = (
                normalized_row.get("merchant")
                or normalized_row.get("payee")
                or normalized_row.get("description")
                or "Unknown Merchant"
            )
            raw_statement = (
                normalized_row.get("original statement")
                or normalized_row.get("statement")
                or normalized_row.get("memo")
                or merchant
            )
            category = normalized_row.get("category") or "Uncategorized"
            account_name = normalized_row.get("account") or "Imported Account"
            amount = self._parse_amount(normalized_row.get("amount") or 0.0)
            notes = normalized_row.get("notes") or ""
            tags_raw = normalized_row.get("tags") or ""
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

            acct_id = f"acct_{hashlib.md5(account_name.lower().encode()).hexdigest()[:8]}"
            if acct_id not in inferred_accounts:
                acct_type = AccountType.CREDIT if "credit" in account_name.lower() else AccountType.DEPOSITORY
                inferred_accounts[acct_id] = Account(
                    id=acct_id,
                    name=account_name,
                    type=acct_type,
                    balance=0.0,
                    provider="csv_import",
                )

            # Generate deterministic transaction ID
            h = hashlib.sha256()
            h.update(f"{acct_id}:{date_iso}:{amount:.2f}:{merchant.lower()}".encode())
            tx_id = f"tx_{h.hexdigest()[:16]}"

            self._transactions.append(
                Transaction(
                    id=tx_id,
                    account_id=acct_id,
                    account_name=account_name,
                    date=date_iso,
                    amount=amount,
                    merchant=merchant,
                    raw_statement=raw_statement,
                    category=category,
                    notes=notes,
                    tags=tags,
                    provider="csv_import",
                )
            )

        if not self._accounts and inferred_accounts:
            self._accounts = list(inferred_accounts.values())

    def _load_json(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw in data.get("accounts", []):
            self._accounts.append(
                Account(
                    id=str(raw["id"]),
                    name=str(raw["name"]),
                    type=AccountType(raw.get("type", "depository")),
                    balance=float(raw.get("balance", 0.0)),
                    currency=str(raw.get("currency", "USD")),
                    mask=str(raw.get("mask", "")),
                    provider="json_import",
                )
            )
        for raw in data.get("transactions", []):
            self._transactions.append(
                Transaction(
                    id=str(raw["id"]),
                    account_id=str(raw["account_id"]),
                    date=str(raw["date"]),
                    amount=float(raw["amount"]),
                    merchant=str(raw["merchant"]),
                    raw_statement=str(raw.get("raw_statement", raw["merchant"])),
                    category=str(raw.get("category", "Uncategorized")),
                    notes=str(raw.get("notes", "")),
                    tags=list(raw.get("tags", [])),
                    provider="json_import",
                )
            )
        for raw in data.get("budgets", []):
            self._budgets.append(
                CategoryBudget(
                    category=str(raw["category"]),
                    budgeted=float(raw["budgeted"]),
                    actual=float(raw.get("actual", 0.0)),
                    remaining=float(raw.get("remaining", raw["budgeted"])),
                )
            )

    async def get_accounts(self) -> list[Account]:
        return list(self._accounts)

    async def get_transactions(
        self,
        start_date: str,
        end_date: str,
        limit: int = 500,
    ) -> list[Transaction]:
        filtered = [
            t for t in self._transactions
            if start_date <= t.date <= end_date
        ]
        return filtered[:limit]

    async def get_budgets(self, month: str | None = None) -> list[CategoryBudget]:
        return list(self._budgets)

    async def get_categories(self) -> list[Category]:
        cats = {t.category for t in self._transactions if t.category}
        return [
            Category(id=f"cat_{hashlib.md5(c.encode()).hexdigest()[:8]}", name=c)
            for c in sorted(cats)
        ]

    @classmethod
    def create_synthetic_fixture(cls, reference_date: datetime | None = None) -> ImportProvider:
        """Create a rich, realistic, 100% synthetic dataset for testing and demonstration."""
        now = reference_date or datetime.now(UTC)
        today_str = now.strftime("%Y-%m-%d")
        d_minus_1 = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        d_minus_3 = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        d_minus_5 = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        d_minus_7 = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        accounts = [
            Account(
                id="acct_checking_1",
                name="Main Household Checking",
                type=AccountType.DEPOSITORY,
                balance=4820.50,
                mask="*8841",
                provider="synthetic",
            ),
            Account(
                id="acct_savings_1",
                name="Emergency High Yield Savings",
                type=AccountType.DEPOSITORY,
                balance=22500.00,
                mask="*3392",
                provider="synthetic",
            ),
            Account(
                id="acct_credit_1",
                name="Sapphire Reserve Credit",
                type=AccountType.CREDIT,
                balance=1450.75,
                mask="*4019",
                provider="synthetic",
            ),
        ]

        budgets = [
            CategoryBudget(category="Groceries", budgeted=900.0, actual=780.0, remaining=120.0),
            CategoryBudget(category="Dining", budgeted=450.0, actual=520.0, remaining=-70.0),  # Over budget!
            CategoryBudget(category="Utilities", budgeted=300.0, actual=280.0, remaining=20.0),
            CategoryBudget(category="Subscriptions", budgeted=100.0, actual=145.0, remaining=-45.0), # Price jump!
            CategoryBudget(category="Rent", budgeted=2200.0, actual=2200.0, remaining=0.0),
        ]

        transactions = [
            # Regular groceries
            Transaction(
                id="syn_tx_1",
                account_id="acct_credit_1",
                account_name="Sapphire Reserve Credit",
                date=today_str,
                amount=115.42,
                merchant="Trader Joe's",
                raw_statement="TRADER JOE #542 SEATTLE WA",
                category="Groceries",
                provider="synthetic",
            ),
            # Dining over-budget charge
            Transaction(
                id="syn_tx_2",
                account_id="acct_credit_1",
                account_name="Sapphire Reserve Credit",
                date=d_minus_1,
                amount=84.20,
                merchant="Osteria La Spiga",
                raw_statement="OSTERIA LA SPIGA SEATTLE",
                category="Dining",
                provider="synthetic",
            ),
            # Duplicate charges (Anomaly test)
            Transaction(
                id="syn_tx_3",
                account_id="acct_credit_1",
                account_name="Sapphire Reserve Credit",
                date=d_minus_3,
                amount=6.75,
                merchant="Blue Bottle Coffee",
                raw_statement="BLUE BOTTLE COFFEE 104",
                category="Dining",
                provider="synthetic",
            ),
            Transaction(
                id="syn_tx_4",
                account_id="acct_credit_1",
                account_name="Sapphire Reserve Credit",
                date=d_minus_3,
                amount=6.75,
                merchant="Blue Bottle Coffee",
                raw_statement="BLUE BOTTLE COFFEE 104",
                category="Dining",
                provider="synthetic",
            ),
            # Large unexpected charge (> $150)
            Transaction(
                id="syn_tx_5",
                account_id="acct_credit_1",
                account_name="Sapphire Reserve Credit",
                date=d_minus_5,
                amount=389.00,
                merchant="Apple Store",
                raw_statement="APPLE STORE #R142 SEATTLE",
                category="Electronics",
                provider="synthetic",
            ),
            # Uncategorized mystery merchant
            Transaction(
                id="syn_tx_6",
                account_id="acct_checking_1",
                account_name="Main Household Checking",
                date=d_minus_5,
                amount=45.00,
                merchant="Apex Cleaners LLC",
                raw_statement="APEX CLEANERS DIR DEB 9912",
                category="Uncategorized",
                provider="synthetic",
            ),
            # Transfer between accounts: Checking outflow, Credit inflow
            Transaction(
                id="syn_tx_7",
                account_id="acct_checking_1",
                account_name="Main Household Checking",
                date=d_minus_7,
                amount=1200.00,
                merchant="Payment to Chase Credit Card",
                raw_statement="CHASE CREDIT CRD EPAY 4019",
                category="Credit Card Payment",
                is_transfer=True,
                provider="synthetic",
            ),
            Transaction(
                id="syn_tx_8",
                account_id="acct_credit_1",
                account_name="Sapphire Reserve Credit",
                date=d_minus_7,
                amount=-1200.00,
                merchant="Automatic Payment - Thank You",
                raw_statement="AUTOPAY PAYMENT RECEIVED - THANK YOU",
                category="Credit Card Payment",
                is_transfer=True,
                provider="synthetic",
            ),
        ]

        return cls(accounts=accounts, transactions=transactions, budgets=budgets)
