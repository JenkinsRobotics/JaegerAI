"""ARES Finance FastAPI sidecar — loopback-only HUD + mutation API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine.card_optimizer import recommend_best_card
from .engine.db import (
    delete_card,
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
    purge_demo_data,
    save_card,
    search_transactions_advanced as db_search_transactions_advanced,
    spending_by_category,
)
from .engine.monarch_sync import MonarchSyncService
from .mcp_server import _with_provenance

VERSION = "1.3.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ARES Finance Sidecar", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _svc() -> MonarchSyncService:
    return MonarchSyncService()


@app.get("/health")
def health_check():
    st = get_sync_state()
    return {
        "status": "ok",
        "service": "ares-finance",
        "version": VERSION,
        "loopback_only": True,
        "is_demo": st["is_demo"],
        "last_sync_at": st["last_sync_at"],
    }


@app.get("/api/status")
def status_endpoint():
    st = get_sync_state()
    return {
        **st,
        "version": VERSION,
        "data_provenance": provenance(),
    }


# ── portfolio & accounts ─────────────────────────────────────────────


@app.get("/api/summary")
def get_financial_summary_endpoint():
    payload = get_financial_summary()
    payload["data_provenance"] = provenance()
    return payload


@app.get("/api/accounts")
def get_accounts():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, type, subtype, current_balance, updated_at "
            "FROM accounts ORDER BY current_balance DESC"
        )
        accounts = [dict(row) for row in cursor.fetchall()]
    return {"accounts": accounts, "data_provenance": provenance()}


class AccountRefreshRequest(BaseModel):
    account_ids: Optional[List[str]] = None


@app.post("/api/accounts/refresh")
async def refresh_accounts_endpoint(req: Optional[AccountRefreshRequest] = None):
    ids = req.account_ids if req else None
    return await _svc().refresh_bank_accounts(account_ids=ids)


@app.get("/api/institutions/health")
async def check_institutions_health():
    return await _svc().get_institution_health()


# ── categories ───────────────────────────────────────────────────────


@app.get("/api/categories")
def get_categories_endpoint():
    return {"categories": get_all_categories(), "data_provenance": provenance()}


class CategoryCreateRequest(BaseModel):
    name: str
    group: str
    icon: Optional[str] = "📁"
    rollover: Optional[bool] = False


@app.post("/api/categories")
async def create_category_endpoint(req: CategoryCreateRequest):
    return await _svc().create_category(
        name=req.name,
        group_id_or_name=req.group,
        icon=req.icon or "📁",
        rollover_enabled=req.rollover or False,
    )


@app.delete("/api/categories/{category_id}")
async def delete_category_endpoint(category_id: str):
    return await _svc().delete_category(category_id)


# ── budgets ──────────────────────────────────────────────────────────


@app.get("/api/budgets")
async def get_budgets_endpoint(live: bool = False):
    if live:
        result = await _svc().get_budgets()
        if result.get("status") == "success":
            result["data_provenance"] = provenance()
            return result
    return {"budgets": get_all_budgets(), "data_provenance": provenance()}


class BudgetSetRequest(BaseModel):
    category: str
    amount: float
    apply_to_future: Optional[bool] = True


@app.post("/api/budgets")
async def set_budget_endpoint(req: BudgetSetRequest):
    return await _svc().set_budget_amount(
        category_name_or_id=req.category,
        amount=req.amount,
        apply_to_future=req.apply_to_future if req.apply_to_future is not None else True,
    )


# ── recurring bills ──────────────────────────────────────────────────


@app.get("/api/recurring-bills")
async def get_recurring_bills_endpoint(live: bool = False):
    if live:
        result = await _svc().get_recurring_transactions()
        if result.get("status") == "success":
            result["data_provenance"] = provenance()
            return result
    return {"recurring_bills": get_all_recurring_bills(), "data_provenance": provenance()}


# ── cards ────────────────────────────────────────────────────────────


@app.get("/api/cards")
def get_cards_api():
    return {"cards": get_all_cards()}


class CardCreateRequest(BaseModel):
    id: str
    name: str
    issuer: str
    rewards: Dict[str, float]
    spend_cap_monthly: Optional[float] = 0.0
    quarterly_category: Optional[str] = ""
    notes: Optional[str] = ""


@app.post("/api/cards")
def create_or_update_card(req: CardCreateRequest):
    save_card(
        req.id,
        req.name,
        req.issuer,
        req.rewards,
        req.spend_cap_monthly or 0.0,
        req.quarterly_category or "",
        req.notes or "",
    )
    return {"status": "saved", "card_id": req.id}


@app.delete("/api/cards/{card_id}")
def delete_card_api(card_id: str):
    success = delete_card(card_id)
    if not success:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"status": "deleted", "card_id": card_id}


# ── transactions ─────────────────────────────────────────────────────


@app.get("/api/transactions")
def get_transactions(limit: int = 50, category: Optional[str] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        if category:
            cursor.execute(
                "SELECT * FROM transactions WHERE category = ? ORDER BY date DESC LIMIT ?",
                (category, limit),
            )
        else:
            cursor.execute("SELECT * FROM transactions ORDER BY date DESC LIMIT ?", (limit,))
        transactions = [dict(row) for row in cursor.fetchall()]
    return {"transactions": transactions, "data_provenance": provenance()}


class TransactionUpdateRequest(BaseModel):
    transaction_id: str
    category: Optional[str] = None
    merchant_name: Optional[str] = None
    notes: Optional[str] = None
    needs_review: Optional[bool] = None


@app.post("/api/transactions/update")
async def update_transaction_endpoint(req: TransactionUpdateRequest):
    return await _svc().update_transaction(
        transaction_id=req.transaction_id,
        category_name_or_id=req.category,
        merchant_name=req.merchant_name,
        notes=req.notes,
        needs_review=req.needs_review,
    )


class TransactionCreateRequest(BaseModel):
    date_str: str
    account_id: str
    amount: float
    merchant_name: str
    category: str
    notes: str = ""


@app.post("/api/transactions")
async def create_transaction_endpoint(req: TransactionCreateRequest):
    return await _svc().create_transaction(
        date_str=req.date_str,
        account_id=req.account_id,
        amount=req.amount,
        merchant_name=req.merchant_name,
        category_name_or_id=req.category,
        notes=req.notes,
    )


@app.get("/api/analytics/spending")
def get_spending_analytics():
    rows = spending_by_category()
    return {
        "spending_by_category": [
            {"category": r["category"], "total_spent": r["total_spent"], "count": r["transactions"]}
            for r in rows
        ],
        "data_provenance": provenance(),
    }


class CardRecommendRequest(BaseModel):
    merchant: str
    category: Optional[str] = None


@app.post("/api/recommend-card")
def recommend_card_api(req: CardRecommendRequest):
    return recommend_best_card(req.merchant, req.category)


class TokenSaveRequest(BaseModel):
    token: str = Field(min_length=1)


@app.post("/api/auth/monarch-token")
async def save_monarch_token(req: TokenSaveRequest):
    return await _svc().save_token(req.token)


class ConnectRequest(BaseModel):
    email: str
    password: str
    mfa_code: Optional[str] = None
    mfa_secret: Optional[str] = None


@app.post("/api/auth/connect")
async def connect_monarch(req: ConnectRequest):
    return await _svc().login_interactive(
        email=req.email,
        password=req.password,
        mfa_code=req.mfa_code,
        mfa_secret=req.mfa_secret,
    )


@app.post("/api/sync")
async def trigger_sync():
    return await _svc().sync_now()



# ── advanced search & cashflow ───────────────────────────────────────


class TransactionSearchRequest(BaseModel):
    query: Optional[str] = None
    since: Optional[str] = None
    until: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    pending_only: Optional[bool] = False
    limit: Optional[int] = 50
    offset: Optional[int] = 0


@app.post("/api/transactions/search")
def search_transactions_advanced(req: TransactionSearchRequest):
    """Advanced transaction search with date range, amount, account, and pagination."""
    return _with_provenance(
        db_search_transactions_advanced(
            query=req.query, since=req.since, until=req.until,
            category=req.category, account_id=req.account_id,
            min_amount=req.min_amount, max_amount=req.max_amount,
            pending_only=req.pending_only or False,
            limit=req.limit or 50, offset=req.offset or 0,
        )
    )


@app.get("/api/analytics/cashflow")
def get_cashflow_local(since: Optional[str] = None, until: Optional[str] = None):
    """Local cashflow summary from cached data."""
    return _with_provenance(db_cashflow_summary(since=since, until=until))


@app.get("/api/analytics/cashflow/live")
async def get_cashflow_live(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Live cashflow summary from Monarch Money."""
    return await _svc().get_cashflow_summary(start_date=start_date, end_date=end_date)


class TransactionDeleteRequest(BaseModel):
    transaction_id: str


@app.delete("/api/transactions/{transaction_id}")
async def delete_transaction_endpoint(transaction_id: str):
    """Delete a transaction from Monarch and local store."""
    return await _svc().delete_transaction(transaction_id=transaction_id)




@app.post("/api/admin/purge-demo")
def purge_demo_endpoint():
    """Delete all demo-seeded data from the database."""
    result = purge_demo_data()
    result["data_provenance"] = provenance()
    return result


if __name__ == "__main__":
    port = int(os.getenv("FINANCE_PORT", 3848))
    host = os.getenv("FINANCE_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
