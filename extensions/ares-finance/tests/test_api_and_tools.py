from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.engine.db import get_auth_value, get_financial_summary, init_db, provenance
from server.mcp_server import list_registered_tools
from server.server import app
from tools import finance_tools

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_tools_match_mcp_and_finance_tools():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    mcp_tools = set(manifest["mcp"]["tools"])
    agent_tools = set(manifest["tools"]["definitions"])
    registered = set(list_registered_tools())
    assert mcp_tools == agent_tools == registered
    for name in sorted(mcp_tools):
        assert callable(getattr(finance_tools, name)), name


def test_manifest_sidecar_is_loopback():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["id"] == "ares-finance"
    assert manifest["sidecar"]["type"] == "loopback"
    assert manifest["sidecar"]["origin"] == "http://127.0.0.1:3848"
    assert manifest["sidecar"]["health_path"] == "/health"
    assert manifest["scripts"] == ["dashboard/app.js"]
    schema_types = {item["type"] for item in manifest["settings_schema"]}
    assert schema_types <= {"boolean", "string", "number", "integer", "enum"}


def test_dashboard_has_budget_and_bills_surfaces():
    html = (ROOT / "dashboard" / "index.html").read_text()
    js = (ROOT / "dashboard" / "app.js").read_text()
    assert 'id="budgetsTab"' in html
    assert 'id="billsTab"' in html
    assert "provenanceBanner" in html
    assert "/api/budgets" in js
    assert "/api/recurring-bills" in js
    assert "/api/auth/connect" in js
    assert "/api/auth/monarch-token" in js


def test_summary_marks_demo_data():
    init_db()
    summary = get_financial_summary()
    prov = provenance()
    assert prov["is_demo"] is True
    assert summary["net_worth"] == 140909.0
    assert "DEMO" in prov["note"]


def test_fastapi_health_and_token_roundtrip():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        assert body["loopback_only"] is True
        assert body["is_demo"] is True

        summary = client.get("/api/summary")
        assert summary.status_code == 200
        assert summary.json()["data_provenance"]["is_demo"] is True

        budgets = client.get("/api/budgets")
        assert budgets.status_code == 200
        assert len(budgets.json()["budgets"]) == 5

        bills = client.get("/api/recurring-bills")
        assert bills.status_code == 200
        assert len(bills.json()["recurring_bills"]) == 5

        blocked = client.post("/api/budgets", json={"category": "Dining", "amount": 500})
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "not_configured"

        saved = client.post("/api/auth/monarch-token", json={"token": "session-token-1"})
        assert saved.status_code == 200
        assert saved.json()["status"] == "authenticated"
        assert get_auth_value("monarch_token") == "session-token-1"


def test_finance_tools_summary_includes_provenance():
    payload = finance_tools.finance_summary()
    assert payload["data_provenance"]["is_demo"] is True
    assert payload["net_worth"] == 140909.0


def test_recommend_card_dining():
    rec = finance_tools.recommend_card("Blue Bottle Coffee")
    assert rec["detected_category"] == "dining"
    assert rec["recommended_card"]["name"] in {"Amex Gold", "Citi Custom Cash", "Chase Sapphire Preferred"}
    assert rec["multiplier"] >= 3.0
