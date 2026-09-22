from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# Isolate the store before any application import.
_BOOT_DIR = Path(tempfile.mkdtemp(prefix="ares-finance-boot-"))
os.environ["ARES_FINANCE_DATA_DIR"] = str(_BOOT_DIR)
os.environ["ARES_FINANCE_DB"] = str(_BOOT_DIR / "finance.db")
os.environ["ARES_FINANCE_SESSION"] = str(_BOOT_DIR / ".mm_session")
os.environ.pop("MONARCH_TOKEN", None)
os.environ.pop("MONARCH_API_KEY", None)
os.environ.pop("MONARCH_EMAIL", None)
os.environ.pop("MONARCH_PASSWORD", None)
os.environ.pop("MONARCH_MFA_SECRET", None)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

CAT_DINING = "11111111-1111-1111-1111-111111111111"
CAT_AI = "33333333-3333-3333-3333-333333333333"
GROUP_FOOD = "22222222-2222-2222-2222-222222222222"
GROUP_TECH = "44444444-4444-4444-4444-444444444444"
ACC_CHECKING = "55555555-5555-5555-5555-555555555555"
TX_SPOTIFY = "66666666-6666-6666-6666-666666666666"


def _month_offset(months: int) -> str:
    today = date.today().replace(day=1)
    year = today.year
    month = today.month + months
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return f"{year:04d}-{month:02d}-01"


class FakeMonarch:
    """In-memory monarchmoney stand-in used by unit tests."""

    def __init__(self) -> None:
        self.created_categories: list[dict] = []
        self.deleted_categories: list[str] = []
        self.budget_sets: list[dict] = []
        self.updated: list[dict] = []
        self.created_tx: list[dict] = []
        self.refresh_calls: list[dict] = []
        self.fail_refresh = False
        self.categories = [
            {
                "id": CAT_DINING,
                "name": "Dining",
                "group": {"id": GROUP_FOOD, "name": "Food & Dining"},
                "isSystemCategory": True,
                "icon": "🍽️",
            },
            {
                "id": CAT_AI,
                "name": "AI Tools",
                "group": {"id": GROUP_TECH, "name": "Tech & Subscriptions"},
                "isSystemCategory": False,
                "icon": "🤖",
            },
        ]
        self.groups = [
            {"id": GROUP_FOOD, "name": "Food & Dining", "categories": [self.categories[0]]},
            {"id": GROUP_TECH, "name": "Tech & Subscriptions", "categories": [self.categories[1]]},
        ]

    async def request_accounts_refresh_and_wait(self, account_ids=None, timeout=300, delay=10):
        self.refresh_calls.append({"account_ids": account_ids, "timeout": timeout, "delay": delay})
        if self.fail_refresh:
            raise RuntimeError("aggregator timeout")
        return True

    async def get_institutions(self):
        return {
            "credentials": [
                {
                    "id": "cred-1",
                    "updateRequired": False,
                    "disconnectedFromDataProviderAt": None,
                    "institution": {"name": "Chase", "hasIssuesReported": False},
                },
                {
                    "id": "cred-2",
                    "updateRequired": True,
                    "disconnectedFromDataProviderAt": "2026-08-01",
                    "institution": {"name": "Broken Bank", "hasIssuesReported": True},
                },
            ]
        }

    async def get_transaction_categories(self):
        return {"categories": self.categories}

    async def get_transaction_category_groups(self):
        return {"categoryGroups": self.groups}

    async def create_transaction_category(self, group_id, transaction_category_name, icon="📁", rollover_enabled=False):
        new_id = "77777777-7777-7777-7777-777777777777"
        cat = {
            "id": new_id,
            "name": transaction_category_name,
            "group": {"id": group_id},
            "isSystemCategory": False,
            "icon": icon,
        }
        self.created_categories.append(cat)
        self.categories.append(cat)
        return {"createCategory": {"category": cat, "errors": None}}

    async def delete_transaction_category(self, category_id):
        self.deleted_categories.append(category_id)
        self.categories = [c for c in self.categories if c["id"] != category_id]
        return True

    async def get_budgets(self, start_date=None, end_date=None):
        monthly = [
            {
                "month": _month_offset(-1),
                "plannedCashFlowAmount": 100.0,
                "actualAmount": -40.0,
                "remainingAmount": 60.0,
            },
            {
                "month": _month_offset(0),
                "plannedCashFlowAmount": 400.0,
                "actualAmount": -120.0,
                "remainingAmount": 280.0,
            },
            {
                "month": _month_offset(1),
                "plannedCashFlowAmount": 999.0,
                "actualAmount": 0.0,
                "remainingAmount": 999.0,
            },
        ]
        return {
            "budgetData": {
                "monthlyAmountsByCategory": [
                    {"category": {"id": CAT_DINING}, "monthlyAmounts": monthly}
                ]
            },
            "categoryGroups": self.groups,
        }

    async def set_budget_amount(self, amount, category_id=None, timeframe="month", start_date=None, apply_to_future=True):
        rec = {
            "amount": amount,
            "category_id": category_id,
            "timeframe": timeframe,
            "start_date": start_date,
            "apply_to_future": apply_to_future,
        }
        self.budget_sets.append(rec)
        return {"ok": True, **rec}

    async def get_recurring_transactions(self, start_date=None, end_date=None):
        if bool(start_date) != bool(end_date):
            raise Exception("You must specify both a start_date and end_date, not just one of them.")
        return {
            "recurringTransactionItems": [
                {
                    "stream": {
                        "id": "stream-spotify",
                        "frequency": "monthly",
                        "amount": -14.99,
                        "merchant": {"name": "Spotify"},
                    },
                    "date": date.today().isoformat(),
                    "isPast": False,
                    "amountDiff": 0,
                    "category": {"name": "Streaming"},
                    "account": {"id": ACC_CHECKING},
                }
            ]
        }

    async def update_transaction(self, transaction_id, **kwargs):
        rec = {"transaction_id": transaction_id, **kwargs}
        self.updated.append(rec)
        return {"ok": True, **rec}

    async def create_transaction(self, date, account_id, amount, merchant_name, category_id, notes="", update_balance=False):
        rec = {
            "id": "88888888-8888-8888-8888-888888888888",
            "date": date,
            "account_id": account_id,
            "amount": amount,
            "merchant_name": merchant_name,
            "category_id": category_id,
            "notes": notes,
        }
        self.created_tx.append(rec)
        return {"createTransaction": {"transaction": rec, "errors": None}}

    async def get_accounts(self):
        return {
            "accounts": [
                {
                    "id": ACC_CHECKING,
                    "displayName": "Checking",
                    "type": {"name": "depository"},
                    "subtype": {"name": "checking"},
                    "currentBalance": 1000.0,
                },
                {
                    "id": "99999999-9999-9999-9999-999999999999",
                    "displayName": "Visa",
                    "type": {"name": "credit"},
                    "subtype": {"name": "credit_card"},
                    "currentBalance": -200.0,
                },
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "displayName": "Brokerage",
                    "type": {"name": "brokerage"},
                    "subtype": {"name": "brokerage"},
                    "currentBalance": 5000.0,
                },
            ]
        }

    async def get_transactions(self, limit=100, offset=0, start_date=None, end_date=None, **_kwargs):
        if offset and offset > 0:
            return {"allTransactions": {"results": []}}
        return {
            "allTransactions": {
                "results": [
                    {
                        "id": TX_SPOTIFY,
                        "account": {"id": ACC_CHECKING},
                        "amount": -14.99,
                        "date": (date.today() - timedelta(days=1)).isoformat(),
                        "merchant": {"name": "Spotify"},
                        "category": {"name": "Streaming"},
                        "notes": "",
                        "pending": False,
                    }
                ]
            }
        }


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_FINANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARES_FINANCE_DB", str(tmp_path / "finance.db"))
    monkeypatch.setenv("ARES_FINANCE_SESSION", str(tmp_path / ".mm_session"))
    monkeypatch.delenv("MONARCH_TOKEN", raising=False)
    monkeypatch.delenv("MONARCH_EMAIL", raising=False)
    monkeypatch.delenv("MONARCH_PASSWORD", raising=False)
    from server.engine.db import init_db

    init_db()
    yield tmp_path


@pytest.fixture
def fake_mm():
    return FakeMonarch()
