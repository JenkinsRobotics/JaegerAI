"""MCP server for ARES Finance.

Exposes the local finance store and Monarch Money automation as Model Context
Protocol tools over stdio for ARES, JaegerAI, and any other MCP client.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x fallback
    from mcp.server.fastmcp import FastMCP as _Server

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

init_db()

mcp = _Server(
    "ares-finance",
    version="1.2.0",
    instructions=(
        "Personal finance tools backed by Monarch Money. "
        "If data_provenance.is_demo is true, figures are FAKE seeded samples — "
        "tell the user and call monarch_status / monarch_setup / sync_monarch. "
        "Mutations (set_budget, create_category, delete_category, edit_transaction, "
        "create_transaction, refresh_bank_accounts) hit the live Monarch API and "
        "fail closed unless a real session exists. Never invent credentials."
    ),
)


def _with_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("data_provenance", provenance())
    return payload


def list_registered_tools() -> list[str]:
    return [t.name for t in mcp._tool_manager.list_tools()]


# ── portfolio & accounts ─────────────────────────────────────────────


@mcp.tool()
def finance_summary() -> dict[str, Any]:
    """Net worth snapshot: total assets, total liabilities, and the balance
    broken down by account type."""
    summary = get_financial_summary()
    return _with_provenance(summary)


@mcp.tool()
def list_accounts() -> dict[str, Any]:
    """Every synced account with its current balance — checking, savings,
    investment, credit, and loans."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, type, subtype, current_balance, updated_at "
            "FROM accounts ORDER BY current_balance DESC"
        )
        accounts = [dict(row) for row in cur.fetchall()]
    return _with_provenance({"accounts": accounts, "count": len(accounts)})


@mcp.tool()
async def refresh_bank_accounts(account_ids: Optional[List[str]] = None) -> dict[str, Any]:
    """Force-refreshes institutions and bank accounts in Monarch Money via
    Plaid/Finicity/MX, then pulls the latest balances into the local store.
    Use this when the user says their accounts are stale or need reconnecting."""
    return await MonarchSyncService().refresh_bank_accounts(account_ids=account_ids)


@mcp.tool()
async def check_institution_health() -> dict[str, Any]:
    """Inspects linked bank and credit card credentials in Monarch to check for
    disconnected institutions, MFA prompts, or data provider errors."""
    return await MonarchSyncService().get_institution_health()


# ── categories & taxonomies ──────────────────────────────────────────


@mcp.tool()
def list_categories() -> dict[str, Any]:
    """List all spending categories and category groups available in your financial store."""
    categories = get_all_categories()
    return _with_provenance({"categories": categories, "count": len(categories)})


@mcp.tool()
async def create_category(
    name: str,
    group: str,
    icon: str = "📁",
    rollover: bool = False,
) -> dict[str, Any]:
    """Create a new custom spending category under an existing category group in Monarch Money.
    Example: name='AI Subscriptions', group='Software' or group='Tech & Subscriptions'.
    Fails if the group does not exist — never silently picks another group."""
    return await MonarchSyncService().create_category(
        name=name, group_id_or_name=group, icon=icon, rollover_enabled=rollover
    )


@mcp.tool()
async def delete_category(category_id_or_name: str) -> dict[str, Any]:
    """Delete a custom spending category from Monarch Money. System categories are refused."""
    return await MonarchSyncService().delete_category(category_id_or_name=category_id_or_name)


# ── budgets & planning ───────────────────────────────────────────────


@mcp.tool()
async def get_budgets(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    live: bool = True,
) -> dict[str, Any]:
    """Get active budget allocations, monthly targets, actual spending, and remaining amounts.
    Pass both start_date and end_date (YYYY-MM-DD) or neither. live=True hits Monarch;
    live=False reads the local cache."""
    if live:
        result = await MonarchSyncService().get_budgets(start_date=start_date, end_date=end_date)
        if result.get("status") == "success":
            return _with_provenance(result)
        cached = get_all_budgets()
        result["budgets"] = result.get("budgets") or cached
        result["count"] = len(result["budgets"])
        result["cache_fallback"] = True
        return _with_provenance(result)
    budgets = get_all_budgets()
    return _with_provenance({"status": "cache", "budgets": budgets, "count": len(budgets)})


@mcp.tool()
async def set_budget(
    category: str,
    amount: float,
    apply_to_future: bool = True,
) -> dict[str, Any]:
    """Set or adjust the monthly budget limit for a specific category in Monarch Money.
    Example: category='Dining', amount=500.0, apply_to_future=True."""
    return await MonarchSyncService().set_budget_amount(
        category_name_or_id=category,
        amount=amount,
        apply_to_future=apply_to_future,
    )


# ── recurring bills & subscriptions ──────────────────────────────────


@mcp.tool()
async def list_recurring_bills(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    live: bool = True,
) -> dict[str, Any]:
    """List recurring bills, subscriptions, utility providers, and payment cadences.
    Pass both start_date and end_date or neither. Use to audit subscriptions and price hikes."""
    if live:
        result = await MonarchSyncService().get_recurring_transactions(
            start_date=start_date, end_date=end_date
        )
        bills = result.get("recurring_bills") or get_all_recurring_bills()
        result["recurring_bills"] = bills
        result["count"] = len(bills)
        result["total_monthly_recurring"] = round(
            sum(b.get("amount", 0) for b in bills if b.get("frequency") == "monthly"),
            2,
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


# ── transactions & ledger ────────────────────────────────────────────


@mcp.tool()
def search_transactions(query: Optional[str] = None, limit: int = 15) -> dict[str, Any]:
    """Search the transaction ledger by merchant name or category, newest first.
    Omit query to get the most recent transactions."""
    results = db_search_transactions(query=query, limit=limit)
    return _with_provenance({"transactions": results, "count": len(results), "query": query})


@mcp.tool()
def spending_by_category(
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
) -> dict[str, Any]:
    """Total spend grouped by category over a date window
    (e.g. 'how much did I spend on groceries this month').
    since/until are ISO dates (YYYY-MM-DD); category is a case-insensitive filter."""
    rows = db_spending_by_category(since=since, until=until, category=category)
    return _with_provenance(
        {
            "spending_by_category": rows,
            "total_spent": round(sum(r["total_spent"] for r in rows), 2),
            "window": {"since": since, "until": until},
            "category_filter": category,
        }
    )


@mcp.tool()
async def edit_transaction(
    transaction_id: str,
    category: Optional[str] = None,
    merchant_name: Optional[str] = None,
    notes: Optional[str] = None,
    needs_review: Optional[bool] = None,
) -> dict[str, Any]:
    """Update a transaction in Monarch Money and sync the change locally.
    Use this to recategorize mislabeled transactions, clean merchant names, or add notes."""
    return await MonarchSyncService().update_transaction(
        transaction_id=transaction_id,
        category_name_or_id=category,
        merchant_name=merchant_name,
        notes=notes,
        needs_review=needs_review,
    )


@mcp.tool()
async def create_transaction(
    date_str: str,
    account_id: str,
    amount: float,
    merchant_name: str,
    category: str,
    notes: str = "",
) -> dict[str, Any]:
    """Manually create and log a transaction into Monarch Money."""
    return await MonarchSyncService().create_transaction(
        date_str=date_str,
        account_id=account_id,
        amount=amount,
        merchant_name=merchant_name,
        category_name_or_id=category,
        notes=notes,
    )


# ── cards ────────────────────────────────────────────────────────────


@mcp.tool()
def recommend_card(merchant: str, category: Optional[str] = None) -> dict[str, Any]:
    """Pick the highest-reward card in your wallet for a purchase at merchant."""
    return recommend_best_card(merchant, category)


@mcp.tool()
def list_cards() -> dict[str, Any]:
    """Every card in the wallet with its reward multipliers and spend caps."""
    cards = get_all_cards()
    return {"cards": cards, "count": len(cards)}


# ── setup & sync ─────────────────────────────────────────────────────


@mcp.tool()
def monarch_status() -> dict[str, Any]:
    """Check whether the store holds real Monarch data or demo data, sync freshness, and next steps."""
    st = get_sync_state()
    if st["is_demo"]:
        next_step = (
            "Not connected. Ask the user for their Monarch email and password "
            "(and a TOTP secret if their account uses MFA), then call "
            "monarch_setup. Until then, every figure in this store is fake."
        )
    elif st["last_status"] != "success":
        next_step = (
            f"Last sync did not succeed ({st['last_status']}: {st['last_error']}). "
            "Stored figures are from the last good sync and may be stale."
        )
    else:
        next_step = "Connected. Call sync_monarch to refresh."
    return {
        "connected": not st["is_demo"],
        "is_demo": st["is_demo"],
        "source": st["source"],
        "last_sync_at": st["last_sync_at"],
        "last_status": st["last_status"],
        "last_error": st["last_error"],
        "synced_accounts": st["synced_accounts"],
        "synced_transactions": st["synced_transactions"],
        "next_step": next_step,
    }


@mcp.tool()
async def monarch_setup(
    email: str,
    password: str,
    mfa_code: Optional[str] = None,
    mfa_secret: Optional[str] = None,
) -> dict[str, Any]:
    """Connect this extension to the user's Monarch Money account.
    Ask the USER for credentials — never invent them. Pass mfa_secret (TOTP secret)
    for fully unattended background syncs."""
    return await MonarchSyncService().login_interactive(
        email=email, password=password, mfa_code=mfa_code, mfa_secret=mfa_secret
    )


@mcp.tool()
async def sync_monarch(days: int = 730) -> dict[str, Any]:
    """Refresh the full local financial store (accounts, transactions, categories,
    budgets, and recurring bills) from Monarch Money."""
    return await MonarchSyncService().sync_now(days=days)



@mcp.tool()
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
) -> dict[str, Any]:
    """Search transactions with advanced filters: date range, amount bounds, account,
    category, and pending status. Supports pagination via limit/offset."""
    return _with_provenance(
        db_search_transactions_advanced(
            query=query, since=since, until=until, category=category,
            account_id=account_id, min_amount=min_amount, max_amount=max_amount,
            pending_only=pending_only, limit=limit, offset=offset,
        )
    )


@mcp.tool()
def cashflow_summary(
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict[str, Any]:
    """Income vs expenses breakdown with savings rate and top expense categories.
    Uses local cache. For live data, call sync_monarch first."""
    return _with_provenance(db_cashflow_summary(since=since, until=until))


@mcp.tool()
async def delete_transaction(transaction_id: str) -> dict[str, Any]:
    """Delete a transaction from Monarch Money and the local store. Returns
    a before/after snapshot. Irreversible — use with care."""
    return await MonarchSyncService().delete_transaction(transaction_id=transaction_id)


@mcp.tool()
async def get_cashflow(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    """Live cashflow summary from Monarch: total income, expenses, net cashflow,
    savings rate, and top expense categories over a date window."""
    return await MonarchSyncService().get_cashflow_summary(
        start_date=start_date, end_date=end_date
    )



def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
