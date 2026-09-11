"""Tests for the autonomous finance feature in jaeger_ai.features.finance."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from jaeger_agent.cognition.commitments import InMemoryCommitmentStore

from jaeger_ai.features.finance import (
    FinanceWorker,
    MonarchService,
    finance_audit,
    finance_summary,
    finance_transactions,
)
from jaeger_ai.features.finance.mission_finance import create_financial_audit_mission


def test_finance_exports():
    assert MonarchService is not None
    assert FinanceWorker is not None
    assert callable(finance_summary)
    assert callable(finance_audit)
    assert callable(finance_transactions)


def test_finance_worker_audit_with_mock_data():
    mock_service = MagicMock(spec=MonarchService)
    mock_service.get_accounts = AsyncMock(return_value={
        "ok": True,
        "account_count": 3,
        "liquid_cash": 8500.0,
        "investments": 45000.0,
        "credit_debt": 1200.0,
        "loan_debt": 0.0,
        "net_worth": 52300.0,
        "accounts": [
            {"name": "Checking", "type": "checking", "balance": 8500.0},
            {"name": "Credit Card", "type": "credit", "balance": -1200.0},
        ],
    })
    mock_service.get_budgets = AsyncMock(return_value={
        "ok": True,
        "categories": [
            {"category": "Dining", "budgeted": 500.0, "actual": 650.0, "remaining": -150.0},
            {"category": "Groceries", "budgeted": 800.0, "actual": 700.0, "remaining": 100.0},
            {"category": "Rent", "budgeted": 2000.0, "actual": 2000.0, "remaining": 0.0},
        ],
    })
    mock_service.get_recent_transactions = AsyncMock(return_value={
        "ok": True,
        "count": 4,
        "transactions": [
            {"id": "1", "merchant": "Apple Store", "amount": 299.0, "category": "Electronics", "date": "2026-09-08"},
            {"id": "2", "merchant": "Coffee Shop", "amount": 6.50, "category": "Dining", "date": "2026-09-09"},
            {"id": "3", "merchant": "Coffee Shop", "amount": 6.50, "category": "Dining", "date": "2026-09-09"},
            {"id": "4", "merchant": "Mystery Vendor", "amount": 42.0, "category": "Uncategorized", "date": "2026-09-10"},
        ],
    })

    worker = FinanceWorker(service=mock_service)
    result = asyncio.run(worker.audit(days=7))

    assert result["ok"] is True
    assert result["accounts_summary"]["net_worth"] == 52300.0
    assert result["accounts_summary"]["liquid_cash"] == 8500.0

    # Over budget check (Dining spent 650 of 500)
    over_budget = result["pacing"]["over_budget"]
    assert any(c["category"] == "Dining" for c in over_budget)

    # Anomaly checks
    anomalies = result["anomalies"]
    assert len(anomalies["large_transactions"]) == 1
    assert anomalies["large_transactions"][0]["merchant"] == "Apple Store"

    assert len(anomalies["duplicates"]) == 1
    assert anomalies["duplicates"][0]["duplicate"]["merchant"] == "Coffee Shop"

    assert len(anomalies["uncategorized"]) == 1
    assert anomalies["uncategorized"][0]["merchant"] == "Mystery Vendor"

    # Briefing markdown check
    briefing = result["briefing"]
    assert "Financial Health & Budget Briefing" in briefing
    assert "Net Worth:" in briefing
    assert "Dining" in briefing


def test_financial_audit_mission_structure():
    store = InMemoryCommitmentStore()
    mission = create_financial_audit_mission(store=store)
    assert "mission" in mission
    assert mission["mission"]["title"] == "Weekly Financial Health & Budget Pacing Audit"
    assert "goals" in mission
    assert len(mission["goals"]) == 4
