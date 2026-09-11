"""Monarch Money service wrapper for JaegerAI.

Session storage (honest):
  Canonical pickle: ``~/.jaeger/finance/mm_session.pickle`` (mode 0600),
  or ``$JAEGER_STATE_DIR/finance/mm_session.pickle`` when set.
  Legacy ``~/.ares/.mm_session.pickle`` is migrated once if present.
  This is a session pickle on disk — not Keychain AES-GCM encryption.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("jaeger_ai.features.finance.monarch")

DEFAULT_API_TIMEOUT_SECONDS = 30.0
MAX_TRANSACTION_DAYS = 365
MAX_TRANSACTION_LIMIT = 500
LEGACY_SESSION_PATH = Path.home() / ".ares" / ".mm_session.pickle"


class MonarchError(Exception):
    """Base typed error for Monarch finance operations."""


class MonarchSessionMissing(MonarchError):
    """Raised when no usable Monarch session pickle is available (fail-closed)."""


class MonarchImportError(MonarchError):
    """Raised when the monarchmoney package cannot be imported."""


class MonarchAPIError(MonarchError):
    """Raised when a Monarch API call fails or times out."""


class MonarchDateError(MonarchError):
    """Raised when start/end date bounds are invalid."""


def _state_root() -> Path:
    raw = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".jaeger").resolve()


def default_session_path() -> Path:
    return _state_root() / "finance" / "mm_session.pickle"


def migrate_legacy_session(new_path: Path | None = None) -> Path:
    """Ensure canonical session path exists; migrate legacy once with a clear log."""
    target = new_path or default_session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 0:
        return target
    legacy = LEGACY_SESSION_PATH
    if legacy.is_file() and legacy.stat().st_size > 0:
        try:
            shutil.copy2(legacy, target)
            os.chmod(target, 0o600)
            logger.info(
                "Migrated Monarch session from legacy path %s -> %s",
                str(legacy),
                str(target),
            )
        except OSError as exc:
            logger.warning("Failed to migrate legacy Monarch session: %s", type(exc).__name__)
            raise MonarchSessionMissing(
                f"Monarch session migrate failed; place session at {target}"
            ) from exc
    return target


def _parse_iso_date(value: str, *, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MonarchDateError(f"Invalid {field}={value!r}; expected YYYY-MM-DD") from exc


def validate_date_bounds(
    start_date: str,
    end_date: str,
    *,
    max_span_days: int = MAX_TRANSACTION_DAYS,
) -> tuple[str, str]:
    """Validate and normalize inclusive ISO date bounds; fail closed on bad input."""
    start = _parse_iso_date(start_date, field="startDate")
    end = _parse_iso_date(end_date, field="endDate")
    if start > end:
        raise MonarchDateError(f"startDate {start_date} is after endDate {end_date}")
    span = (end - start).days
    if span > max_span_days:
        raise MonarchDateError(
            f"Date span {span}d exceeds max {max_span_days}d"
        )
    today = datetime.now(UTC).date()
    if end > today + timedelta(days=1):
        raise MonarchDateError(f"endDate {end_date} is in the far future")
    return start.isoformat(), end.isoformat()


class MonarchService:
    """Service wrapping Monarch Money GraphQL API (fail-closed without session)."""

    def __init__(
        self,
        session_path: Path | None = None,
        *,
        timeout_seconds: float = DEFAULT_API_TIMEOUT_SECONDS,
        migrate: bool = True,
    ) -> None:
        if session_path is None and migrate:
            self.session_path = migrate_legacy_session()
        else:
            self.session_path = session_path or default_session_path()
        self.timeout_seconds = float(timeout_seconds)
        self._mm: Any = None

    def is_session_available(self) -> bool:
        """Check if the session pickle file exists and is non-empty."""
        try:
            return self.session_path.is_file() and self.session_path.stat().st_size > 0
        except OSError:
            return False

    def _require_session(self) -> None:
        if not self.is_session_available():
            raise MonarchSessionMissing(
                f"Monarch Money session not found at {self.session_path}. "
                "Connect via the Monarch sheet or login command."
            )

    def _get_client(self) -> Any:
        """Instantiate MonarchMoney client and load saved session (no secret logging)."""
        if self._mm is not None:
            return self._mm

        self._require_session()

        try:
            from monarchmoney import MonarchMoney
        except ImportError as exc:
            raise MonarchImportError(
                "monarchmoney package is not installed. "
                "Install via `uv pip install monarchmoney 'gql<4'`."
            ) from exc

        try:
            mm = MonarchMoney(session_file=str(self.session_path))
            mm.load_session(str(self.session_path))
        except MonarchError:
            raise
        except Exception as exc:  # noqa: BLE001 — library raises mixed types
            # Never log exception args (may contain tokens); type only.
            logger.warning("Failed to load Monarch session: %s", type(exc).__name__)
            raise MonarchSessionMissing(
                f"Monarch session unreadable at {self.session_path}"
            ) from exc

        self._mm = mm
        return self._mm

    async def _call(self, coro: Any, *, op: str) -> Any:
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        except TimeoutError as exc:
            logger.warning("Monarch API timeout on %s after %.1fs", op, self.timeout_seconds)
            raise MonarchAPIError(f"Monarch API timeout on {op}") from exc
        except MonarchError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Monarch API error on %s: %s", op, type(exc).__name__)
            raise MonarchAPIError(f"Monarch API error on {op}: {type(exc).__name__}") from exc

    async def get_accounts(self) -> dict[str, Any]:
        """Fetch all connected financial accounts and calculate aggregate balances."""
        try:
            self._require_session()
            client = self._get_client()
            raw = await self._call(client.get_accounts(), op="get_accounts")
        except MonarchError as exc:
            return {"ok": False, "error": str(exc), "accounts": []}

        accounts_list: list[dict[str, Any]] = (
            raw.get("accounts", []) if isinstance(raw, dict) else list(raw or [])
        )

        liquid_cash = 0.0
        credit_debt = 0.0
        loan_debt = 0.0
        investments = 0.0
        parsed_accounts: list[dict[str, Any]] = []

        for acct in accounts_list[:200]:  # hard bound
            name = acct.get("displayName") or acct.get("name") or "Unnamed Account"
            balance = float(acct.get("currentBalance") or 0.0)
            raw_type = acct.get("type", {})
            type_name = (
                raw_type.get("name") if isinstance(raw_type, dict) else str(raw_type or "")
            ).lower()

            parsed_accounts.append({
                "id": acct.get("id"),
                "name": name,
                "type": type_name,
                "balance": balance,
                "updated_at": acct.get("updatedAt"),
                "is_hidden": acct.get("isHidden", False),
            })

            if "depository" in type_name or "checking" in type_name or "savings" in type_name:
                liquid_cash += balance
            elif "credit" in type_name:
                credit_debt += abs(balance)
            elif "loan" in type_name or "mortgage" in type_name:
                loan_debt += abs(balance)
            elif "investment" in type_name or "brokerage" in type_name:
                investments += balance

        net_worth = (liquid_cash + investments) - (credit_debt + loan_debt)

        return {
            "ok": True,
            "account_count": len(parsed_accounts),
            "liquid_cash": round(liquid_cash, 2),
            "investments": round(investments, 2),
            "credit_debt": round(credit_debt, 2),
            "loan_debt": round(loan_debt, 2),
            "net_worth": round(net_worth, 2),
            "accounts": parsed_accounts,
        }

    async def get_recent_transactions(
        self,
        days: int = 7,
        limit: int = 100,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch transactions for a bounded date window (startDate/endDate verified)."""
        days = max(1, min(int(days), MAX_TRANSACTION_DAYS))
        limit = max(1, min(int(limit), MAX_TRANSACTION_LIMIT))

        now = datetime.now(UTC)
        if start_date is None or end_date is None:
            end_d = now.strftime("%Y-%m-%d")
            start_d = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        else:
            start_d, end_d = start_date, end_date

        try:
            start_d, end_d = validate_date_bounds(start_d, end_d)
            self._require_session()
            client = self._get_client()
            raw = await self._call(
                client.get_transactions(limit=limit, start_date=start_d, end_date=end_d),
                op="get_transactions",
            )
        except MonarchError as exc:
            return {"ok": False, "error": str(exc), "transactions": []}

        tx_list = (
            raw.get("allTransactions", {}).get("results", [])
            if isinstance(raw, dict)
            else list(raw or [])
        )
        parsed: list[dict[str, Any]] = []
        for tx in tx_list[:limit]:
            category = tx.get("category") or {}
            cat_name = (
                category.get("name")
                if isinstance(category, dict)
                else str(category or "Uncategorized")
            )
            merchant = tx.get("merchant") or {}
            merchant_name = (
                merchant.get("name")
                if isinstance(merchant, dict)
                else tx.get("plaidName") or "Unknown"
            )
            account = tx.get("account") or {}
            account_name = (
                account.get("displayName", "Account")
                if isinstance(account, dict)
                else "Account"
            )

            parsed.append({
                "id": tx.get("id"),
                "date": tx.get("date"),
                "amount": float(tx.get("amount") or 0.0),
                "merchant": merchant_name,
                "category": cat_name,
                "pending": tx.get("pending", False),
                "account": account_name,
            })

        return {
            "ok": True,
            "count": len(parsed),
            "since": start_d,
            "until": end_d,
            "transactions": parsed,
        }

    async def get_budgets(self) -> dict[str, Any]:
        """Fetch current month budget targets and actual spending."""
        now = datetime.now(UTC)
        start_date = now.strftime("%Y-%m-01")
        import calendar

        _, days_in_month = calendar.monthrange(now.year, now.month)
        end_date = now.strftime(f"%Y-%m-{days_in_month:02d}")
        try:
            start_date, end_date = validate_date_bounds(start_date, end_date)
            self._require_session()
            client = self._get_client()
            raw = await self._call(
                client.get_budgets(start_date=start_date, end_date=end_date),
                op="get_budgets",
            )
        except MonarchError as exc:
            return {"ok": False, "error": str(exc), "categories": []}

        category_budgets: list[dict[str, Any]] = []
        raw_cats = (
            raw.get("budgetData", {}).get("categories", []) if isinstance(raw, dict) else []
        )

        for c in raw_cats[:200]:
            cat_obj = c.get("category", {}) if isinstance(c, dict) else {}
            name = cat_obj.get("name", "Category") if isinstance(cat_obj, dict) else "Category"
            budgeted = float(c.get("budgetedAmount") or 0.0)
            actual = float(c.get("actualAmount") or 0.0)
            category_budgets.append({
                "category": name,
                "budgeted": budgeted,
                "actual": actual,
                "remaining": round(budgeted - actual, 2),
            })

        return {
            "ok": True,
            "month": now.strftime("%B %Y"),
            "startDate": start_date,
            "endDate": end_date,
            "categories": category_budgets,
        }

    def get_accounts_sync(self) -> dict[str, Any]:
        """Synchronous wrapper for get_accounts."""
        return asyncio.run(self.get_accounts())

    def get_recent_transactions_sync(self, days: int = 7, limit: int = 100) -> dict[str, Any]:
        """Synchronous wrapper for get_recent_transactions."""
        return asyncio.run(self.get_recent_transactions(days=days, limit=limit))

    def get_budgets_sync(self) -> dict[str, Any]:
        """Synchronous wrapper for get_budgets."""
        return asyncio.run(self.get_budgets())


# Back-compat alias used by older call sites / docs
DEFAULT_SESSION_PATH = default_session_path()
