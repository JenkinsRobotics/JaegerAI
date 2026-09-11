"""Tests for the autonomous finance feature in jaeger_ai.features.finance."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jaeger_agent.cognition.commitments import InMemoryCommitmentStore

from jaeger_ai.features.finance import (
    FinanceWorker,
    MonarchDateError,
    MonarchService,
    MonarchSessionMissing,
    default_session_path,
    finance_audit,
    finance_summary,
    finance_transactions,
    migrate_legacy_session,
    validate_date_bounds,
)
from jaeger_ai.features.finance.mission_finance import create_financial_audit_mission


def test_finance_exports():
    assert MonarchService is not None
    assert FinanceWorker is not None
    assert callable(finance_summary)
    assert callable(finance_audit)
    assert callable(finance_transactions)


def test_default_session_path_under_jaeger(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    path = default_session_path()
    assert path == tmp_path / "finance" / "mm_session.pickle"
    assert ".ares" not in str(path)


def test_migrate_legacy_session_once(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    legacy = tmp_path / "legacy" / ".mm_session.pickle"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"fake-session-bytes")

    monkeypatch.setattr(
        "jaeger_ai.features.finance.monarch_service.LEGACY_SESSION_PATH",
        legacy,
    )

    from jaeger_ai.features.finance.monarch_service import migrate_legacy_session

    target = tmp_path / "state" / "finance" / "mm_session.pickle"
    result = migrate_legacy_session()
    assert result == target
    assert target.is_file()
    assert target.read_bytes() == b"fake-session-bytes"
    assert oct(target.stat().st_mode & 0o777) == "0o600"

    # Second call does not overwrite if target exists
    legacy.write_bytes(b"changed")
    result2 = migrate_legacy_session()
    assert result2.read_bytes() == b"fake-session-bytes"


def test_validate_date_bounds_ok_and_fail():
    start, end = validate_date_bounds("2026-01-01", "2026-01-31")
    assert start == "2026-01-01"
    assert end == "2026-01-31"

    with pytest.raises(MonarchDateError):
        validate_date_bounds("2026-02-01", "2026-01-01")

    with pytest.raises(MonarchDateError):
        validate_date_bounds("not-a-date", "2026-01-01")

    with pytest.raises(MonarchDateError):
        validate_date_bounds("2020-01-01", "2026-01-01")  # span > 365


def test_fail_closed_without_session(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    service = MonarchService(session_path=tmp_path / "missing.pickle", migrate=False)
    assert service.is_session_available() is False
    with pytest.raises(MonarchSessionMissing):
        service._require_session()

    async def _run():
        res = await service.get_accounts()
        assert res["ok"] is False
        assert "session" in res["error"].lower() or "not found" in res["error"].lower()

    asyncio.run(_run())


def test_finance_worker_audit_with_mock_data(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    mock_service = MagicMock(spec=MonarchService)
    mock_service.is_session_available.return_value = True
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

    over_budget = result["pacing"]["over_budget"]
    assert any(c["category"] == "Dining" for c in over_budget)

    anomalies = result["anomalies"]
    assert len(anomalies["large_transactions"]) == 1
    assert anomalies["large_transactions"][0]["merchant"] == "Apple Store"

    assert len(anomalies["duplicates"]) == 1
    assert anomalies["duplicates"][0]["duplicate"]["merchant"] == "Coffee Shop"

    assert len(anomalies["uncategorized"]) == 1
    assert anomalies["uncategorized"][0]["merchant"] == "Mystery Vendor"

    briefing = result["briefing"]
    assert "Financial Health & Budget Briefing" in briefing
    assert "Net Worth:" in briefing
    assert "Dining" in briefing

    # Report only under ~/.jaeger/reports/finance (via JAEGER_STATE_DIR)
    report = Path(result["report_path"])
    assert report.name == "latest.json"
    assert "reports" in report.parts and "finance" in report.parts
    assert report.is_file()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["ok"] is True


def test_finance_worker_catches_api_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    mock_service = MagicMock(spec=MonarchService)
    mock_service.is_session_available.return_value = True
    mock_service.get_accounts = AsyncMock(side_effect=MonarchSessionMissing("gone"))
    mock_service.get_budgets = AsyncMock()
    mock_service.get_recent_transactions = AsyncMock()
    worker = FinanceWorker(service=mock_service)
    result = asyncio.run(worker.audit(days=7))
    assert result["ok"] is False
    assert "gone" in result["error"]


def test_finance_worker_fail_closed_no_session(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    mock_service = MagicMock(spec=MonarchService)
    mock_service.is_session_available.return_value = False
    worker = FinanceWorker(service=mock_service)
    result = asyncio.run(worker.audit(days=7))
    assert result["ok"] is False


def test_financial_audit_mission_structure():
    store = InMemoryCommitmentStore()
    mission = create_financial_audit_mission(store=store)
    assert "mission" in mission
    assert mission["mission"]["title"] == "Weekly Financial Health & Budget Pacing Audit"
    assert "goals" in mission
    assert len(mission["goals"]) == 4
