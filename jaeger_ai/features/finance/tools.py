"""Agent-facing tools for personal finance management via the normalized Finance Engine."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .anomaly import AnomalyDetector
from .approval import ApprovalEngine
from .briefing import BriefingEngine
from .budget import BudgetEngine
from .cashflow import CashFlowEngine
from .classifier import TransactionClassifier
from .memory import FinanceMemory
from .models import ReviewStatus
from .providers.importer import ImportProvider
from .providers.monarch import MonarchProvider
from .store import FinanceStore
from .sync import SyncEngine

logger = logging.getLogger("jaeger_ai.features.finance.tools")


def _get_store() -> FinanceStore:
    return FinanceStore()


def _get_provider(store: FinanceStore) -> Any:
    monarch = MonarchProvider()
    if monarch.is_available():
        return monarch
    # Fallback to imported/synthetic provider if store has records or Monarch unavailable
    return ImportProvider()


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_summary",
    summary="get financial net worth, liquid cash, credit card balances, and checking runway",
)
def finance_summary() -> dict[str, Any]:
    """Retrieve aggregate net worth, liquid cash runway, credit card debt, and balances."""
    store = _get_store()
    cashflow = CashFlowEngine(store)
    runway = cashflow.calculate_runway()
    accounts = [a.to_dict() for a in store.get_accounts()]

    # If local store is empty, attempt sync if monarch available
    if not accounts:
        monarch = MonarchProvider()
        if monarch.is_available():
            engine = SyncEngine(store, monarch)
            asyncio.run(engine.sync(days=14))
            runway = cashflow.calculate_runway()
            accounts = [a.to_dict() for a in store.get_accounts()]

    return {
        "ok": True,
        "net_worth": runway["net_worth"],
        "liquid_checking": runway["liquid_checking"],
        "liquid_savings": runway["liquid_savings"],
        "total_liquid": runway["total_liquid"],
        "credit_debt": runway["credit_card_debt"],
        "loan_debt": runway["loan_debt"],
        "checking_runway_days": runway["checking_runway_days"],
        "shortfall_warning": runway.get("shortfall_warning"),
        "account_count": len(accounts),
        "accounts": accounts[:20],
    }


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_audit",
    summary="audit budget pacing, spending speed, and transaction anomalies",
)
def finance_audit(days: int = 7) -> dict[str, Any]:
    """Audit monthly budget pacing, fast-spending categories, duplicate charges, and spikes."""
    store = _get_store()
    briefing_engine = BriefingEngine(store)
    weekly = briefing_engine.generate_weekly_briefing()

    return {
        "ok": True,
        "briefing": weekly["markdown"],
        "pacing": weekly["pacing"],
        "runway": weekly["runway"],
        "anomalies": weekly["anomalies"],
    }


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_transactions",
    summary="list recent transactions across accounts with classification metadata",
)
def finance_transactions(days: int = 7, limit: int = 50) -> dict[str, Any]:
    """Fetch recent cleared and pending transactions with category and explanation."""
    store = _get_store()
    txs = store.get_transactions(limit=limit)
    return {
        "ok": True,
        "count": len(txs),
        "transactions": [t.to_dict() for t in txs],
    }


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_inbox",
    summary="review unreviewed, uncategorized, low-confidence, or duplicate transactions",
)
def finance_inbox(limit: int = 20) -> dict[str, Any]:
    """Review transactions in the inbox awaiting classification approval or review."""
    store = _get_store()
    classifier = TransactionClassifier(store)
    classifier.classify_all_new()
    inbox = classifier.get_inbox_items()

    return {
        "ok": True,
        "count": len(inbox),
        "items": inbox[:limit],
    }


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_sync",
    summary="idempotently synchronize accounts and transactions into local encrypted storage",
)
def finance_sync(days: int = 30) -> dict[str, Any]:
    """Trigger idempotent synchronization from configured provider (Monarch or CSV)."""
    store = _get_store()
    provider = _get_provider(store)
    engine = SyncEngine(store, provider)
    summary = asyncio.run(engine.sync(days=days))
    # Automatically run classification pass
    classifier = TransactionClassifier(store)
    classified_count = classifier.classify_all_new()

    res = summary.to_dict()
    res["classified_count"] = classified_count
    return res


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_briefing",
    summary="produce daily, weekly, or monthly executive briefings",
)
def finance_briefing(cadence: str = "weekly") -> dict[str, Any]:
    """Generate daily, weekly, or monthly financial briefing markdown."""
    store = _get_store()
    briefing_engine = BriefingEngine(store)
    cad = cadence.lower().strip()
    if cad == "daily":
        return briefing_engine.generate_daily_briefing()
    elif cad == "monthly":
        return briefing_engine.generate_monthly_close()
    else:
        return briefing_engine.generate_weekly_briefing()
