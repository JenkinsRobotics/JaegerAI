from __future__ import annotations

import asyncio

from server.engine.db import (
    find_category,
    get_all_budgets,
    get_all_categories,
    get_auth_value,
    get_financial_summary,
    get_sync_state,
    get_transaction,
    set_auth_value,
)
from server.engine.monarch_sync import (
    MonarchSyncService,
    looks_like_monarch_id,
    normalize_account_type,
    pick_budget_month,
)
from tests.conftest import CAT_AI, CAT_DINING, GROUP_FOOD, TX_SPOTIFY


def test_looks_like_monarch_id():
    assert looks_like_monarch_id(CAT_DINING)
    assert not looks_like_monarch_id("cat_dining")
    assert not looks_like_monarch_id("")
    assert not looks_like_monarch_id(None)


def test_normalize_account_type():
    assert normalize_account_type({"name": "brokerage"}) == "investment"
    assert normalize_account_type("credit card") == "credit"
    assert normalize_account_type("checking") == "depository"
    assert normalize_account_type("loan") == "loan"


def test_pick_budget_month_prefers_current_not_last():
    rows = [
        {"month": "2026-07-01", "plannedCashFlowAmount": 1},
        {"month": "2026-08-01", "plannedCashFlowAmount": 2},
        {"month": "2026-09-01", "plannedCashFlowAmount": 999},
    ]
    picked = pick_budget_month(rows, prefer="2026-08")
    assert picked["plannedCashFlowAmount"] == 2


def test_mutation_requires_auth():
    result = asyncio.run(MonarchSyncService().set_budget_amount("Dining", 500))
    assert result["status"] == "not_configured"
    assert "credentials" in result["error"].lower() or "configured" in result["error"].lower()


def test_create_category_unknown_group_is_fail_closed(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).create_category("Widgets", "Does Not Exist"))
    assert result["status"] == "failed"
    assert fake_mm.created_categories == []
    assert "not found" in result["error"].lower()


def test_create_category_does_not_use_first_group(fake_mm):
    result = asyncio.run(
        MonarchSyncService(client=fake_mm).create_category("Cloud Infra", "Tech & Subscriptions")
    )
    assert result["status"] == "success"
    assert fake_mm.created_categories[0]["group"]["id"] == "44444444-4444-4444-4444-444444444444"
    assert result["before"]["category"] is None
    assert result["after"]["name"] == "Cloud Infra"


def test_demo_category_id_is_not_sent_to_monarch(fake_mm):
    demo = find_category("Dining")
    assert demo is not None
    assert demo["id"] == "cat_dining"
    result = asyncio.run(MonarchSyncService(client=fake_mm).set_budget_amount("cat_dining", 10))
    assert result["status"] == "failed"
    assert fake_mm.budget_sets == []


def test_set_budget_resolves_live_name_and_returns_diff(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).set_budget_amount("Dining", 500))
    assert result["status"] == "success"
    assert fake_mm.budget_sets[0]["category_id"] == CAT_DINING
    assert result["after"]["new_budget_amount"] == 500
    assert result["before"]["amount"] == 400.0
    assert result["before"]["spent"] == 120.0


def test_get_budgets_uses_current_month_not_next(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).get_budgets())
    assert result["status"] == "success"
    assert result["budgets"][0]["amount"] == 400.0
    assert result["budgets"][0]["spent"] == 120.0
    assert result["budgets"][0]["category_name"] == "Dining"


def test_get_budgets_rejects_half_window(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).get_budgets(start_date="2026-08-01"))
    assert result["status"] == "failed"
    assert "both" in result["error"]


def test_delete_refuses_system_category(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).delete_category("Dining"))
    assert result["status"] == "failed"
    assert "system" in result["error"].lower()
    assert fake_mm.deleted_categories == []


def test_delete_custom_category(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).delete_category("AI Tools"))
    assert result["status"] == "success"
    assert fake_mm.deleted_categories == [CAT_AI]
    assert result["before"]["name"] == "AI Tools"
    assert result["after"] is None


def test_edit_transaction_before_after(fake_mm):
    from server.engine.db import save_transaction

    save_transaction(TX_SPOTIFY, "acc", -14.99, "2026-08-10", "Spotify", "Streaming", source="monarch")
    result = asyncio.run(
        MonarchSyncService(client=fake_mm).update_transaction(
            TX_SPOTIFY, category_name_or_id="AI Tools", notes="SaaS"
        )
    )
    assert result["status"] == "success"
    assert result["before"]["category"] == "Streaming"
    assert result["after"]["category"] == "AI Tools"
    assert get_transaction(TX_SPOTIFY)["notes"] == "SaaS"
    assert fake_mm.updated[0]["category_id"] == CAT_AI


def test_create_transaction_writes_local_row(fake_mm):
    result = asyncio.run(
        MonarchSyncService(client=fake_mm).create_transaction(
            date_str="2026-08-20",
            account_id="55555555-5555-5555-5555-555555555555",
            amount=-20.0,
            merchant_name="Cursor",
            category_name_or_id="AI Tools",
        )
    )
    assert result["status"] == "success"
    assert result["before"] is None
    assert get_transaction(result["transaction_id"])["merchant_name"] == "Cursor"


def test_token_from_db_is_used():
    set_auth_value("monarch_token", "tok_abc")
    svc = MonarchSyncService()
    assert svc._token() == "tok_abc"
    assert get_auth_value("monarch_token") == "tok_abc"


def test_sync_purges_demo_and_normalizes_types(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).sync_now(days=30))
    assert result["status"] == "success"
    assert result["synced"] is True
    state = get_sync_state()
    assert state["source"] == "monarch"
    assert state["is_demo"] is False
    cats = get_all_categories()
    assert cats
    assert all(c["source"] == "monarch" for c in cats)
    assert not any(c["id"].startswith("cat_") for c in cats)
    summary = get_financial_summary()
    assert summary["total_assets"] == 6000.0
    assert summary["total_liabilities"] == 200.0
    assert summary["net_worth"] == 5800.0
    assert summary["breakdown"]["investment"] == 5000.0
    budgets = get_all_budgets()
    assert budgets[0]["amount"] == 400.0


def test_refresh_then_sync(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).refresh_bank_accounts())
    assert result["status"] == "success"
    assert fake_mm.refresh_calls
    assert result["sync_summary"]["synced"] is True


def test_institution_health_flags_reconnect(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).get_institution_health())
    assert result["issues_detected"] == 1
    assert result["issues"][0]["institution"]["name"] == "Broken Bank"


def test_recurring_bills_parse(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).get_recurring_transactions())
    assert result["status"] == "success"
    assert result["recurring_bills"][0]["merchant_name"] == "Spotify"
    assert result["recurring_bills"][0]["amount"] == 14.99



# ── New feature tests ────────────────────────────────────────────────


def test_search_transactions_advanced_date_filter():
    from server.engine.db import search_transactions_advanced, init_db
    init_db()
    result = search_transactions_advanced(since="2026-08-01", until="2026-08-31")
    assert result["count"] >= 0
    assert "total_count" in result
    assert "transactions" in result


def test_search_transactions_advanced_category_filter():
    from server.engine.db import search_transactions_advanced, init_db
    init_db()
    result = search_transactions_advanced(category="Dining")
    assert result["count"] >= 0
    for tx in result["transactions"]:
        assert "dining" in tx.get("category", "").lower()


def test_search_transactions_advanced_amount_filter():
    from server.engine.db import search_transactions_advanced, init_db
    init_db()
    result = search_transactions_advanced(min_amount=10.0, max_amount=100.0)
    assert result["count"] >= 0
    for tx in result["transactions"]:
        assert abs(tx["amount"]) >= 10.0 - 0.01
        assert abs(tx["amount"]) <= 100.0 + 0.01


def test_search_transactions_advanced_pagination():
    from server.engine.db import search_transactions_advanced, init_db
    init_db()
    page1 = search_transactions_advanced(limit=2, offset=0)
    page2 = search_transactions_advanced(limit=2, offset=2)
    assert page1["limit"] == 2
    assert page1["offset"] == 0
    assert page2["offset"] == 2
    # Pages should not overlap
    ids1 = {tx["id"] for tx in page1["transactions"]}
    ids2 = {tx["id"] for tx in page2["transactions"]}
    assert ids1.isdisjoint(ids2)


def test_cashflow_summary_local():
    from server.engine.db import get_cashflow_summary, init_db
    init_db()
    result = get_cashflow_summary()
    assert "total_income" in result
    assert "total_expenses" in result
    assert "net_cashflow" in result
    assert "savings_rate" in result
    assert "top_expense_categories" in result
    assert isinstance(result["top_expense_categories"], list)


def test_cashflow_summary_with_window():
    from server.engine.db import get_cashflow_summary, init_db
    init_db()
    result = get_cashflow_summary(since="2026-08-01", until="2026-08-31")
    assert result["window"]["since"] == "2026-08-01"
    assert result["window"]["until"] == "2026-08-31"


def test_delete_transaction_requires_auth():
    result = asyncio.run(MonarchSyncService().delete_transaction("tx_01"))
    assert result["status"] == "not_configured"


def test_delete_transaction_with_fake_mm(fake_mm):
    from server.engine.db import save_transaction, get_transaction, init_db
    init_db()
    save_transaction("tx_del_test", "acc_checking", -5.0, "2026-08-20", "Test Merchant", "Dining", source="monarch")
    assert get_transaction("tx_del_test") is not None
    result = asyncio.run(MonarchSyncService(client=fake_mm).delete_transaction("tx_del_test"))
    assert result["status"] == "success"
    assert result["before"]["merchant_name"] == "Test Merchant"
    assert result["after"] is None
    assert get_transaction("tx_del_test") is None


def test_cashflow_live_requires_auth():
    result = asyncio.run(MonarchSyncService().get_cashflow_summary())
    assert result["status"] == "not_configured"


def test_cashflow_live_with_fake_mm(fake_mm):
    result = asyncio.run(MonarchSyncService(client=fake_mm).get_cashflow_summary())
    assert result["status"] == "success"
    assert "total_income" in result
    assert "total_expenses" in result
    assert "net_cashflow" in result
    assert "savings_rate" in result
    assert "top_expense_categories" in result
    assert result["transaction_count"] >= 1


def test_mcp_tools_include_new_entries():
    from server.mcp_server import list_registered_tools
    tools = list_registered_tools()
    assert "search_transactions_advanced" in tools
    assert "cashflow_summary" in tools
    assert "delete_transaction" in tools
    assert "get_cashflow" in tools


def test_finance_tools_has_new_functions():
    import tools.finance_tools as ft
    assert callable(getattr(ft, "search_transactions_advanced", None))
    assert callable(getattr(ft, "cashflow_summary", None))
    assert callable(getattr(ft, "delete_transaction", None))
    assert callable(getattr(ft, "get_cashflow", None))
