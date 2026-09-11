"""Agent-facing tools for personal finance management via Monarch Money."""

from __future__ import annotations

import asyncio
from typing import Any

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .finance_worker import FinanceWorker
from .monarch_service import MonarchService


def _get_worker() -> FinanceWorker:
    return FinanceWorker()


def _get_service() -> MonarchService:
    return MonarchService()


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_summary",
    summary="get financial net worth, liquid cash, and debt balances",
)
def finance_summary() -> dict[str, Any]:
    """Retrieve current net worth, total liquid cash, credit card balances,
    and loan totals from connected Monarch Money accounts.
    """
    service = _get_service()
    if not service.is_session_available():
        return {
            "ok": False,
            "error": "Monarch Money is not connected. Connect via the Monarch auth sheet in Jaeger chat or use `/finance`.",
        }
    try:
        res = asyncio.run(service.get_accounts())
        return res
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_audit",
    summary="audit budget pacing, spending speed, and transaction anomalies",
)
def finance_audit(days: int = 7) -> dict[str, Any]:
    """Audit monthly budget pacing, highlight categories that are spending too
    quickly given the current day of the month, and flag unusual or duplicate
    transactions.
    """
    worker = _get_worker()
    if not worker.service.is_session_available():
        return {
            "ok": False,
            "error": "Monarch Money is not connected. Connect via the Monarch auth sheet in Jaeger chat or use `/finance`.",
        }
    try:
        res = asyncio.run(worker.audit(days=days))
        return res
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
@requires_tier(
    PermissionTier.READ_ONLY,
    skill="finance",
    operation="finance_transactions",
    summary="list recent transactions across all accounts",
)
def finance_transactions(days: int = 7, limit: int = 50) -> dict[str, Any]:
    """Fetch recent cleared and pending transactions from all connected financial accounts."""
    service = _get_service()
    if not service.is_session_available():
        return {
            "ok": False,
            "error": "Monarch Money is not connected. Connect via the Monarch auth sheet in Jaeger chat or use `/finance`.",
        }
    try:
        res = asyncio.run(service.get_recent_transactions(days=days, limit=limit))
        return res
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
