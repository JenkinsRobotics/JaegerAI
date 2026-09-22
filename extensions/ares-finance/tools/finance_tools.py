"""Direct ARES agent tools — same surface as the MCP server, sync wrappers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.engine.card_optimizer import recommend_best_card
from server.engine.db import (
    get_all_budgets,
    get_all_cards,
    get_all_categories,
    get_all_recurring_bills,
    get_cashflow_summary as db_cashflow_summary,
    get_db,
    get_financial_summary,
    get_sync_state,
    init_db,
    provenance,
    search_transactions as db_search_transactions,
    search_transactions_advanced as db_search_transactions_advanced,
    spending_by_category as db_spending_by_category,
)
from server.engine.monarch_sync import MonarchSyncService
from server.engine.runtime import run_async

init_db()


def _with_provenance(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload.setdefault("data_provenance", provenance())
    return payload


def finance_summary() -> Dict[str, Any]:
    """Returns a snapshot of liquid assets, investments, liabilities, and net worth."""
    return _with_provenance(get_financial_summary())


def list_accounts() -> Dict[str, Any]:
    """Lists all accounts and current balances."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, type, subtype, current_balance, updated_at "
            "FROM accounts ORDER BY current_balance DESC"
        )
        return _with_provenance({"accounts": [dict(row) for row in cursor.fetchall()]})


def refresh_bank_accounts(account_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Force-refreshes bank account balances from source aggregators."""
    return run_async(lambda: MonarchSyncService().refresh_bank_accounts(account_ids=account_ids))


def check_institution_health() -> Dict[str, Any]:
    """Audits linked banks for MFA prompts, expired logins, or provider errors."""
    return run_async(lambda: MonarchSyncService().get_institution_health())


def list_categories() -> Dict[str, Any]:
    """Lists all spending categories and groups."""
    cats = get_all_categories()
    return _with_provenance({"categories": cats, "count": len(cats)})


def create_category(name: str, group: str, icon: str = "📁", rollover: bool = False) -> Dict[str, Any]:
    """Creates a new spending category in Monarch Money."""
    return run_async(
        lambda: MonarchSyncService().create_category(
            name=name, group_id_or_name=group, icon=icon, rollover_enabled=rollover
        )
    )


def delete_category(category_id_or_name: str) -> Dict[str, Any]:
    """Deletes a custom spending category from Monarch Money."""
    return run_async(lambda: MonarchSyncService().delete_category(category_id_or_name=category_id_or_name))


def get_budgets(
    start_date: Optional[str] = None, end_date: Optional[str] = None, live: bool = True
) -> Dict[str, Any]:
    """Retrieves budget amounts vs actual spending."""
    if live:
        result = run_async(
            lambda: MonarchSyncService().get_budgets(start_date=start_date, end_date=end_date)
        )
        if result.get("status") != "success":
            cached = get_all_budgets()
            result["budgets"] = result.get("budgets") or cached
            result["count"] = len(result["budgets"])
            result["cache_fallback"] = True
        return _with_provenance(result)
    budgets = get_all_budgets()
    return _with_provenance({"status": "cache", "budgets": budgets, "count": len(budgets)})


def set_budget(category: str, amount: float, apply_to_future: bool = True) -> Dict[str, Any]:
    """Sets the monthly budget limit for a category."""
    return run_async(
        lambda: MonarchSyncService().set_budget_amount(
            category_name_or_id=category, amount=amount, apply_to_future=apply_to_future
        )
    )


def list_recurring_bills(
    start_date: Optional[str] = None, end_date: Optional[str] = None, live: bool = True
) -> Dict[str, Any]:
    """Lists all recurring bills, subscriptions, and providers."""
    if live:
        result = run_async(
            lambda: MonarchSyncService().get_recurring_transactions(
                start_date=start_date, end_date=end_date
            )
        )
        bills = result.get("recurring_bills") or get_all_recurring_bills()
        result["recurring_bills"] = bills
        result["count"] = len(bills)
        result["total_monthly_recurring"] = round(
            sum(b.get("amount", 0) for b in bills if b.get("frequency") == "monthly"), 2
        )
        if result.get("status") != "success":
            result["cache_fallback"] = True
        return _with_provenance(result)
    bills = get_all_recurring_bills()
    return _with_provenance(
        {
            "status": "cache",
            "recurring_bills": bills,
            "count": len(bills),
            "total_monthly_recurring": round(
                sum(b["amount"] for b in bills if b.get("frequency") == "monthly"), 2
            ),
        }
    )


def recommend_card(merchant: str, category: Optional[str] = None) -> Dict[str, Any]:
    """Evaluates the optimal credit card in your wallet for a merchant purchase."""
    return recommend_best_card(merchant, category)


def list_cards() -> Dict[str, Any]:
    """Every card in the wallet with reward multipliers and spend caps."""
    cards = get_all_cards()
    return {"cards": cards, "count": len(cards)}


def search_transactions(query: Optional[str] = None, limit: int = 15) -> Dict[str, Any]:
    """Searches recent transaction ledger by merchant name or category."""
    results = db_search_transactions(query=query, limit=limit)
    return _with_provenance({"transactions": results, "count": len(results)})


def spending_by_category(
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Total spend grouped by category over an ISO date window."""
    rows = db_spending_by_category(since=since, until=until, category=category)
    return _with_provenance(
        {
            "spending_by_category": rows,
            "total_spent": round(sum(r["total_spent"] for r in rows), 2),
            "window": {"since": since, "until": until},
            "category_filter": category,
        }
    )


def edit_transaction(
    transaction_id: str,
    category: Optional[str] = None,
    merchant_name: Optional[str] = None,
    notes: Optional[str] = None,
    needs_review: Optional[bool] = None,
) -> Dict[str, Any]:
    """Updates a transaction in Monarch and locally."""
    return run_async(
        lambda: MonarchSyncService().update_transaction(
            transaction_id=transaction_id,
            category_name_or_id=category,
            merchant_name=merchant_name,
            notes=notes,
            needs_review=needs_review,
        )
    )


def create_transaction(
    date_str: str,
    account_id: str,
    amount: float,
    merchant_name: str,
    category: str,
    notes: str = "",
) -> Dict[str, Any]:
    """Manually logs a transaction into Monarch Money."""
    return run_async(
        lambda: MonarchSyncService().create_transaction(
            date_str=date_str,
            account_id=account_id,
            amount=amount,
            merchant_name=merchant_name,
            category_name_or_id=category,
            notes=notes,
        )
    )



def search_transactions_advanced(
    query: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
    account_id: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    pending_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Advanced transaction search with date range, amount bounds, account, category,
    and pending status filters. Supports pagination."""
    return _with_provenance(
        db_search_transactions_advanced(
            query=query, since=since, until=until, category=category,
            account_id=account_id, min_amount=min_amount, max_amount=max_amount,
            pending_only=pending_only, limit=limit, offset=offset,
        )
    )


def cashflow_summary(
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Local cashflow summary: income, expenses, net, savings rate, top categories."""
    return _with_provenance(db_cashflow_summary(since=since, until=until))


def delete_transaction(transaction_id: str) -> Dict[str, Any]:
    """Deletes a transaction from Monarch Money and the local store. Irreversible."""
    return run_async(
        lambda: MonarchSyncService().delete_transaction(transaction_id=transaction_id)
    )


def get_cashflow(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Live cashflow summary from Monarch: income, expenses, net, savings rate."""
    return run_async(
        lambda: MonarchSyncService().get_cashflow_summary(
            start_date=start_date, end_date=end_date
        )
    )



def monarch_status() -> Dict[str, Any]:
    """Connection status, demo vs real data, and last sync timestamp."""
    st = get_sync_state()
    return {
        "connected": not st["is_demo"],
        "is_demo": st["is_demo"],
        "source": st["source"],
        "last_sync_at": st["last_sync_at"],
        "last_status": st["last_status"],
        "last_error": st["last_error"],
        "synced_accounts": st["synced_accounts"],
        "synced_transactions": st["synced_transactions"],
    }


def monarch_setup(
    email: str,
    password: str,
    mfa_code: Optional[str] = None,
    mfa_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """Connect to Monarch with operator-supplied credentials."""
    return run_async(
        lambda: MonarchSyncService().login_interactive(
            email=email, password=password, mfa_code=mfa_code, mfa_secret=mfa_secret
        )
    )


def sync_monarch(days: int = 730) -> Dict[str, Any]:
    """Triggers a full sync against Monarch Money."""
    return run_async(lambda: MonarchSyncService().sync_now(days=days))
