"""Monarch Money sync & mutation engine.

Mutations always resolve categories/groups against the live Monarch API (or an
injected test client). Demo SQLite ids such as ``cat_dining`` are never sent
to GraphQL. Every mutation returns a before/after snapshot.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .db import (
    delete_category_from_db,
    find_category,
    get_auth_value,
    get_sync_state,
    get_transaction,
    provenance,
    purge_demo_data,
    save_budget,
    save_category,
    save_recurring_bill,
    save_transaction,
    session_file_path,
    set_auth_value,
    set_sync_state,
    update_transaction_in_db,
    get_db,
)

logger = logging.getLogger("ares.finance.sync")

DEFAULT_SYNC_DAYS = 730
PAGE_SIZE = 100
MAX_PAGES = 200
REFRESH_TIMEOUT_DEFAULT = 300

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

ACCOUNT_TYPE_MAP = {
    "depository": "depository",
    "checking": "depository",
    "savings": "depository",
    "cash": "depository",
    "prepaid": "depository",
    "credit": "credit",
    "credit card": "credit",
    "credit_card": "credit",
    "loan": "loan",
    "mortgage": "loan",
    "student": "loan",
    "auto": "loan",
    "brokerage": "investment",
    "investment": "investment",
    "ira": "investment",
    "401k": "investment",
    "roth": "investment",
    "retirement": "investment",
}


class MonarchAuthError(RuntimeError):
    """Authentication could not be established — with a reason the agent can act on."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def looks_like_monarch_id(value: Optional[str]) -> bool:
    return bool(value and UUID_RE.match(value.strip()))


def normalize_account_type(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("display") or ""
    key = str(raw or "unknown").strip().lower()
    return ACCOUNT_TYPE_MAP.get(key, key or "unknown")


def pick_budget_month(monthly: List[dict], prefer: Optional[str] = None) -> dict:
    """Return the current (or closest) month row, never blindly the last item."""
    if not monthly:
        return {}
    prefer = (prefer or date.today().strftime("%Y-%m"))[:7]

    def month_key(item: dict) -> str:
        return str(item.get("month") or "")[:7]

    for item in monthly:
        if month_key(item) == prefer:
            return item

    current = date.today().replace(day=1)

    def parsed(item: dict) -> date:
        s = month_key(item)
        try:
            year, month = s.split("-")
            return date(int(year), int(month), 1)
        except (ValueError, TypeError):
            return date.min

    return min(monthly, key=lambda item: abs((parsed(item) - current).days))


def _graphql_errors(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if not errors:
        return None
    if isinstance(errors, str):
        return errors
    if isinstance(errors, list):
        parts = []
        for err in errors:
            if isinstance(err, dict):
                parts.append(str(err.get("message") or err))
            else:
                parts.append(str(err))
        return "; ".join(parts) if parts else str(errors)
    return str(errors)


class MonarchSyncService:
    """Synchronizes and automates Monarch Money data and operations."""

    def __init__(self, client: Any = None) -> None:
        self._injected_client = client
        self.is_syncing = False

    def _token(self) -> str:
        return (
            os.getenv("MONARCH_TOKEN", "")
            or os.getenv("MONARCH_API_KEY", "")
            or (get_auth_value("monarch_token") or "")
        )

    def _email(self) -> str:
        return os.getenv("MONARCH_EMAIL", "") or (get_auth_value("monarch_email") or "")

    def _password(self) -> str:
        return os.getenv("MONARCH_PASSWORD", "") or (get_auth_value("monarch_password") or "")

    def _mfa_secret(self) -> str:
        return os.getenv("MONARCH_MFA_SECRET", "") or (get_auth_value("monarch_mfa_secret") or "")

    @staticmethod
    def _sdk_client(token: Optional[str] = None):
        try:
            from monarchmoney import MonarchMoney
        except ImportError as exc:
            raise MonarchAuthError(
                "sdk_missing",
                "The 'monarchmoney' package is not installed. "
                "Install it with: pip install -r requirements.txt",
            ) from exc
        path = session_file_path()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        return MonarchMoney(session_file=path, token=token or None)

    async def _authenticate(self):
        if self._injected_client is not None:
            return self._injected_client

        from monarchmoney import LoginFailedException, RequireMFAException

        token = self._token()
        if token:
            return self._sdk_client(token=token)

        client = self._sdk_client()
        session = session_file_path()
        if os.path.exists(session):
            try:
                client.load_session(session)
                return client
            except Exception as exc:  # noqa: BLE001
                logger.info("Saved Monarch session unusable (%s); re-authenticating.", exc)

        email, password = self._email(), self._password()
        if not (email and password):
            raise MonarchAuthError(
                "not_configured",
                "No Monarch credentials configured. Run the 'monarch_setup' tool, "
                "save a token in the Finance tab, or set MONARCH_EMAIL and "
                "MONARCH_PASSWORD (plus MONARCH_MFA_SECRET if MFA is enabled).",
            )
        try:
            await client.login(
                email=email,
                password=password,
                use_saved_session=True,
                save_session=True,
                mfa_secret_key=self._mfa_secret() or None,
            )
        except RequireMFAException as exc:
            raise MonarchAuthError(
                "mfa_required",
                "Monarch requires multi-factor authentication. Provide the TOTP "
                "secret as MONARCH_MFA_SECRET (preferred, works unattended), or "
                "pass a one-time code to the 'monarch_setup' tool.",
            ) from exc
        except LoginFailedException as exc:
            raise MonarchAuthError(
                "login_failed", f"Monarch rejected the credentials: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise MonarchAuthError(
                "network_error", f"Could not reach Monarch: {type(exc).__name__}: {exc}"
            ) from exc
        return client

    def _auth_failure(self, exc: MonarchAuthError) -> dict[str, Any]:
        set_sync_state(status=exc.status, error=exc.message)
        return {
            "status": exc.status,
            "error": exc.message,
            "message": exc.message,
            "synced": False,
            "data_provenance": provenance(),
        }

    async def login_interactive(
        self,
        email: str,
        password: str,
        mfa_code: Optional[str] = None,
        mfa_secret: Optional[str] = None,
    ) -> dict[str, Any]:
        if self._injected_client is not None:
            set_sync_state(status="authenticated", error=None)
            return {
                "status": "authenticated",
                "message": "Injected test client — session treated as established.",
            }

        from monarchmoney import LoginFailedException, RequireMFAException

        client = self._sdk_client()
        try:
            if mfa_code:
                await client.multi_factor_authenticate(email, password, mfa_code)
            else:
                await client.login(
                    email=email,
                    password=password,
                    use_saved_session=False,
                    save_session=True,
                    mfa_secret_key=mfa_secret or None,
                )
        except RequireMFAException:
            return {
                "status": "mfa_required",
                "message": "Monarch sent a multi-factor code. Call monarch_setup "
                "again with the same email and password plus mfa_code, or supply "
                "mfa_secret (the TOTP secret) for unattended logins.",
            }
        except LoginFailedException as exc:
            return {"status": "login_failed", "message": f"Monarch rejected the credentials: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "network_error",
                "message": f"Could not reach Monarch: {type(exc).__name__}: {exc}",
            }

        session = session_file_path()
        try:
            client.save_session(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist Monarch session: %s", exc)

        token = getattr(client, "token", None) or getattr(client, "_token", None)
        if token:
            set_auth_value("monarch_token", str(token))

        set_sync_state(status="authenticated", error=None)
        return {
            "status": "authenticated",
            "message": "Monarch session established and saved. Run sync_monarch to "
            "pull your accounts and transactions.",
            "session_file": session,
        }

    async def save_token(self, token: str) -> dict[str, Any]:
        token = (token or "").strip()
        if not token:
            return {"status": "failed", "error": "Token is empty."}
        set_auth_value("monarch_token", token)
        set_sync_state(status="authenticated", error=None)
        return {
            "status": "authenticated",
            "message": "Monarch token saved. Run sync_monarch to pull live data.",
        }

    # ── live category / group resolution ─────────────────────────────

    async def _live_categories(self, client) -> list[dict[str, Any]]:
        data = await client.get_transaction_categories()
        return (data or {}).get("categories", []) or []

    async def _live_groups(self, client) -> list[dict[str, Any]]:
        data = await client.get_transaction_category_groups()
        return (data or {}).get("categoryGroups", []) or []

    async def resolve_category(self, client, name_or_id: str) -> dict[str, Any]:
        """Resolve a category against live Monarch data. Never uses demo ids."""
        needle = (name_or_id or "").strip()
        if not needle:
            return {"status": "failed", "error": "Category name or id is required."}

        categories = await self._live_categories(client)
        if looks_like_monarch_id(needle):
            for cat in categories:
                if cat.get("id") == needle:
                    return {"status": "ok", "category": cat}
            return {
                "status": "failed",
                "error": f"No Monarch category with id '{needle}'.",
            }

        exact = [c for c in categories if (c.get("name") or "").lower() == needle.lower()]
        if len(exact) == 1:
            return {"status": "ok", "category": exact[0]}
        if len(exact) > 1:
            return {
                "status": "failed",
                "error": f"Category name '{needle}' is ambiguous ({len(exact)} matches). Use the category id.",
                "matches": [{"id": c.get("id"), "name": c.get("name")} for c in exact],
            }

        partial = [c for c in categories if needle.lower() in (c.get("name") or "").lower()]
        if len(partial) == 1:
            return {"status": "ok", "category": partial[0]}
        if len(partial) > 1:
            return {
                "status": "failed",
                "error": f"Category '{needle}' matches {len(partial)} live categories. Be more specific or use an id.",
                "matches": [{"id": c.get("id"), "name": c.get("name")} for c in partial],
            }

        cached = find_category(needle, monarch_only=True)
        if cached and looks_like_monarch_id(cached.get("id")):
            return {
                "status": "ok",
                "category": {
                    "id": cached["id"],
                    "name": cached["name"],
                    "group": {"id": cached.get("group_id"), "name": cached.get("group_name")},
                    "isSystemCategory": bool(cached.get("is_system")),
                },
            }

        return {
            "status": "failed",
            "error": f"Category '{needle}' was not found in Monarch. "
            "Call list_categories after sync_monarch, then retry with the exact name or UUID.",
        }

    async def resolve_group(self, client, name_or_id: str) -> dict[str, Any]:
        needle = (name_or_id or "").strip()
        if not needle:
            return {"status": "failed", "error": "Category group name or id is required."}
        groups = await self._live_groups(client)
        if looks_like_monarch_id(needle):
            for group in groups:
                if group.get("id") == needle:
                    return {"status": "ok", "group": group}
        exact = [g for g in groups if (g.get("name") or "").lower() == needle.lower()]
        if len(exact) == 1:
            return {"status": "ok", "group": exact[0]}
        if len(exact) > 1:
            return {
                "status": "failed",
                "error": f"Group '{needle}' is ambiguous. Use the group id.",
                "matches": [{"id": g.get("id"), "name": g.get("name")} for g in exact],
            }
        partial = [g for g in groups if needle.lower() in (g.get("name") or "").lower()]
        if len(partial) == 1:
            return {"status": "ok", "group": partial[0]}
        names = [g.get("name") for g in groups if g.get("name")]
        return {
            "status": "failed",
            "error": f"Category group '{needle}' not found. Available groups: {', '.join(names) or '(none)'}.",
        }

    # ── bank account refresh & institution health ────────────────────

    async def refresh_bank_accounts(
        self,
        account_ids: Optional[List[str]] = None,
        timeout: int = REFRESH_TIMEOUT_DEFAULT,
        sync_after: bool = True,
    ) -> dict[str, Any]:
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        try:
            success = await client.request_accounts_refresh_and_wait(
                account_ids=account_ids, timeout=timeout, delay=10
            )
            sync_res = None
            if sync_after:
                sync_res = await self.sync_now(client=client)
            return {
                "status": "success" if success else "timeout",
                "refreshed": bool(success),
                "account_ids": account_ids or "all",
                "sync_summary": sync_res,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bank refresh failed: %s", exc)
            return {"status": "failed", "error": str(exc), "refreshed": False}

    async def get_institution_health(self) -> dict[str, Any]:
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        try:
            data = await client.get_institutions()
            credentials = data.get("credentials", []) or []
            issues = []
            for cred in credentials:
                institution = cred.get("institution") or {}
                if (
                    cred.get("updateRequired")
                    or cred.get("disconnectedFromDataProviderAt")
                    or institution.get("hasIssuesReported")
                ):
                    issues.append(cred)
            return {
                "status": "success",
                "total_institutions": len(credentials),
                "credentials": credentials,
                "issues_detected": len(issues),
                "issues": issues,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    # ── categories ───────────────────────────────────────────────────

    async def get_categories(self, sync_to_db: bool = True, client=None) -> dict[str, Any]:
        try:
            client = client or await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        try:
            categories = await self._live_categories(client)
            groups = await self._live_groups(client)
            group_map = {g.get("id"): g.get("name") for g in groups}
            formatted = []
            for cat in categories:
                group = cat.get("group") or {}
                g_id = group.get("id")
                g_name = group_map.get(g_id) or group.get("name") or "Other"
                cat_dict = {
                    "id": cat.get("id"),
                    "name": cat.get("name"),
                    "group_id": g_id,
                    "group_name": g_name,
                    "icon": cat.get("icon") or "📁",
                    "is_system": bool(cat.get("isSystemCategory") or cat.get("systemCategory")),
                }
                formatted.append(cat_dict)
                if sync_to_db and cat_dict["id"]:
                    save_category(
                        cat_id=cat_dict["id"],
                        name=cat_dict["name"],
                        group_id=cat_dict["group_id"],
                        group_name=cat_dict["group_name"],
                        icon=cat_dict["icon"],
                        is_system=cat_dict["is_system"],
                        source="monarch",
                    )
            return {
                "status": "success",
                "categories": formatted,
                "category_groups": groups,
                "count": len(formatted),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    async def create_category(
        self,
        name: str,
        group_id_or_name: str,
        icon: str = "📁",
        rollover_enabled: bool = False,
    ) -> dict[str, Any]:
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        resolved = await self.resolve_group(client, group_id_or_name)
        if resolved.get("status") != "ok":
            return resolved
        group = resolved["group"]
        before = {"category": None, "group": {"id": group.get("id"), "name": group.get("name")}}
        try:
            res = await client.create_transaction_category(
                group_id=group["id"],
                transaction_category_name=name,
                icon=icon,
                rollover_enabled=rollover_enabled,
            )
            payload = (res or {}).get("createCategory") or {}
            err = _graphql_errors(payload)
            if err:
                return {"status": "failed", "error": err, "before": before, "after": None}
            cat_obj = payload.get("category") or {}
            cat_id = cat_obj.get("id")
            if not cat_id:
                return {"status": "failed", "error": "Monarch did not return a category id.", "response": res}
            save_category(
                cat_id=cat_id,
                name=name,
                group_id=group.get("id"),
                group_name=group.get("name"),
                icon=icon,
                is_system=False,
                source="monarch",
            )
            after = {
                "id": cat_id,
                "name": name,
                "group_name": group.get("name"),
                "icon": icon,
            }
            return {
                "status": "success",
                "category": after,
                "before": before,
                "after": after,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    async def delete_category(self, category_id_or_name: str) -> dict[str, Any]:
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        resolved = await self.resolve_category(client, category_id_or_name)
        if resolved.get("status") != "ok":
            return resolved
        cat = resolved["category"]
        if cat.get("isSystemCategory") or cat.get("systemCategory"):
            return {
                "status": "failed",
                "error": f"Refusing to delete system category '{cat.get('name')}'.",
            }
        before = {"id": cat.get("id"), "name": cat.get("name")}
        try:
            success = await client.delete_transaction_category(category_id=cat["id"])
            if success:
                delete_category_from_db(cat["id"])
                return {
                    "status": "success",
                    "deleted_category_id": cat["id"],
                    "before": before,
                    "after": None,
                }
            return {"status": "failed", "message": "Monarch did not confirm deletion.", "before": before}
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc), "before": before}

    # ── budgets ──────────────────────────────────────────────────────

    def _parse_budget_item(
        self,
        item: dict,
        cat_name_map: dict[str, str],
        prefer_month: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        cat_id = (item.get("category") or {}).get("id")
        if not cat_id:
            return None
        monthly = item.get("monthlyAmounts") or []
        latest = pick_budget_month(monthly, prefer=prefer_month)
        planned = float(latest.get("plannedCashFlowAmount") or 0.0)
        actual_raw = latest.get("actualAmount")
        actual = float(actual_raw or 0.0)
        spent = abs(actual)
        remaining_raw = latest.get("remainingAmount")
        remaining = float(remaining_raw) if remaining_raw is not None else round(planned - spent, 2)
        month_period = str(latest.get("month") or prefer_month or "current")[:10]
        return {
            "id": f"{cat_id}_{month_period}",
            "category_id": cat_id,
            "category_name": cat_name_map.get(cat_id) or "Category",
            "amount": round(planned, 2),
            "spent": round(spent, 2),
            "remaining": round(remaining, 2),
            "period": month_period,
        }

    async def get_budgets(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sync_to_db: bool = True,
        client=None,
    ) -> dict[str, Any]:
        if bool(start_date) != bool(end_date):
            return {
                "status": "failed",
                "error": "Provide both start_date and end_date, or neither.",
            }
        try:
            client = client or await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        try:
            data = await client.get_budgets(start_date=start_date, end_date=end_date)
            budget_data = data.get("budgetData", {}) or {}
            cat_amounts = budget_data.get("monthlyAmountsByCategory", []) or []
            groups = data.get("categoryGroups", []) or []
            cat_name_map: dict[str, str] = {}
            for group in groups:
                for cat in group.get("categories") or []:
                    if cat.get("id"):
                        cat_name_map[cat["id"]] = cat.get("name") or "Category"
            prefer = (end_date or date.today().isoformat())[:7]
            parsed_budgets = []
            for item in cat_amounts:
                entry = self._parse_budget_item(item, cat_name_map, prefer_month=prefer)
                if not entry:
                    continue
                parsed_budgets.append(entry)
                if sync_to_db:
                    save_budget(
                        budget_id=entry["id"],
                        category_id=entry["category_id"],
                        category_name=entry["category_name"],
                        amount=entry["amount"],
                        spent=entry["spent"],
                        remaining=entry["remaining"],
                        period=entry["period"],
                        source="monarch",
                    )
            return {"status": "success", "budgets": parsed_budgets, "count": len(parsed_budgets)}
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    async def set_budget_amount(
        self,
        category_name_or_id: str,
        amount: float,
        timeframe: str = "month",
        start_date: Optional[str] = None,
        apply_to_future: bool = True,
    ) -> dict[str, Any]:
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        resolved = await self.resolve_category(client, category_name_or_id)
        if resolved.get("status") != "ok":
            return resolved
        cat = resolved["category"]
        cat_id = cat["id"]
        cat_name = cat.get("name") or category_name_or_id
        before_budgets = await self.get_budgets(client=client, sync_to_db=False)
        before_row = next(
            (b for b in before_budgets.get("budgets") or [] if b.get("category_id") == cat_id),
            None,
        )
        try:
            res = await client.set_budget_amount(
                amount=float(amount),
                category_id=cat_id,
                timeframe=timeframe,
                start_date=start_date,
                apply_to_future=apply_to_future,
            )
            save_budget(
                budget_id=f"{cat_id}_current",
                category_id=cat_id,
                category_name=cat_name,
                amount=float(amount),
                spent=(before_row or {}).get("spent", 0.0),
                remaining=round(float(amount) - float((before_row or {}).get("spent", 0.0) or 0.0), 2),
                period="current",
                source="monarch",
            )
            after = {
                "category": cat_name,
                "category_id": cat_id,
                "new_budget_amount": float(amount),
                "apply_to_future": apply_to_future,
            }
            return {
                "status": "success",
                **after,
                "before": before_row,
                "after": after,
                "monarch_response": res,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    # ── recurring bills ──────────────────────────────────────────────

    async def get_recurring_transactions(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sync_to_db: bool = True,
        client=None,
    ) -> dict[str, Any]:
        if bool(start_date) != bool(end_date):
            return {
                "status": "failed",
                "error": "Provide both start_date and end_date, or neither.",
            }
        try:
            client = client or await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        try:
            res = await client.get_recurring_transactions(start_date=start_date, end_date=end_date)
            items = res.get("recurringTransactionItems", []) or []
            parsed_bills = []
            for item in items:
                stream = item.get("stream") or {}
                merchant = stream.get("merchant") or {}
                merchant_name = merchant.get("name") or "Unknown Provider"
                amount = float(stream.get("amount") or item.get("amount") or 0.0)
                frequency = stream.get("frequency") or "monthly"
                cat = (item.get("category") or {}).get("name") or "Recurring / Bills"
                acc_id = (item.get("account") or {}).get("id")
                bill_id = stream.get("id") or item.get("transactionId") or f"bill_{merchant_name}"
                next_date = item.get("date")
                bill_entry = {
                    "id": bill_id,
                    "merchant_name": merchant_name,
                    "category_name": cat,
                    "amount": round(abs(amount), 2),
                    "frequency": frequency,
                    "next_date": next_date,
                    "status": "active",
                    "account_id": acc_id,
                    "is_past": bool(item.get("isPast")),
                    "amount_diff": item.get("amountDiff"),
                }
                parsed_bills.append(bill_entry)
                if sync_to_db:
                    save_recurring_bill(
                        bill_id=bill_id,
                        merchant_name=merchant_name,
                        category_name=cat,
                        amount=abs(amount),
                        frequency=frequency,
                        next_date=next_date,
                        status="active",
                        account_id=acc_id,
                        source="monarch",
                    )
            return {
                "status": "success",
                "recurring_bills": parsed_bills,
                "count": len(parsed_bills),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    # ── cashflow & analytics ─────────────────────────────────────────

    async def get_cashflow_summary(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        client=None,
    ) -> dict[str, Any]:
        """Income vs expenses breakdown over a date window."""
        try:
            client = client or await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        try:
            end = end_date or date.today().isoformat()
            start = start_date or (date.today() - timedelta(days=30)).isoformat()
            transactions = await self._fetch_all_transactions(client, start, end)
            income = 0.0
            expenses = 0.0
            by_category: dict[str, float] = {}
            for tx in transactions:
                amount = float(tx.get("amount") or 0.0)
                cat = (tx.get("category") or {}).get("name") or "Uncategorized"
                if amount >= 0:
                    income += amount
                else:
                    expenses += abs(amount)
                    by_category[cat] = by_category.get(cat, 0.0) + abs(amount)
            top_categories = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:10]
            return {
                "status": "success",
                "start_date": start,
                "end_date": end,
                "total_income": round(income, 2),
                "total_expenses": round(expenses, 2),
                "net_cashflow": round(income - expenses, 2),
                "savings_rate": round((income - expenses) / income * 100, 1) if income else 0.0,
                "top_expense_categories": [
                    {"category": c, "amount": round(a, 2)} for c, a in top_categories
                ],
                "transaction_count": len(transactions),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    # ── transaction mutations ────────────────────────────────────────

    async def update_transaction(
        self,
        transaction_id: str,
        category_name_or_id: Optional[str] = None,
        merchant_name: Optional[str] = None,
        notes: Optional[str] = None,
        needs_review: Optional[bool] = None,
        hide_from_reports: Optional[bool] = None,
        amount: Optional[float] = None,
        date_str: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)

        category_id = None
        category_display = category_name_or_id
        if category_name_or_id:
            resolved = await self.resolve_category(client, category_name_or_id)
            if resolved.get("status") != "ok":
                return resolved
            category_id = resolved["category"]["id"]
            category_display = resolved["category"].get("name") or category_name_or_id

        before = get_transaction(transaction_id)
        try:
            res = await client.update_transaction(
                transaction_id=transaction_id,
                category_id=category_id,
                merchant_name=merchant_name,
                notes=notes,
                needs_review=needs_review,
                hide_from_reports=hide_from_reports,
                amount=amount,
                date=date_str,
            )
            err = _graphql_errors(res) if isinstance(res, dict) else None
            if err:
                return {"status": "failed", "error": err, "before": before, "after": None}
            update_transaction_in_db(
                tx_id=transaction_id,
                category=category_display,
                merchant_name=merchant_name,
                notes=notes,
            )
            after = {
                "transaction_id": transaction_id,
                "category": category_display,
                "merchant_name": merchant_name,
                "notes": notes,
                "needs_review": needs_review,
            }
            return {
                "status": "success",
                "transaction_id": transaction_id,
                "updated_fields": after,
                "before": before,
                "after": after,
                "monarch_response": res,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc), "before": before}

    async def create_transaction(
        self,
        date_str: str,
        account_id: str,
        amount: float,
        merchant_name: str,
        category_name_or_id: str,
        notes: str = "",
        update_balance: bool = False,
    ) -> dict[str, Any]:
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        resolved = await self.resolve_category(client, category_name_or_id)
        if resolved.get("status") != "ok":
            return resolved
        cat = resolved["category"]
        before = None
        try:
            res = await client.create_transaction(
                date=date_str,
                account_id=account_id,
                amount=amount,
                merchant_name=merchant_name,
                category_id=cat["id"],
                notes=notes,
                update_balance=update_balance,
            )
            payload = (res or {}).get("createTransaction") or {}
            err = _graphql_errors(payload)
            if err:
                return {"status": "failed", "error": err, "before": before, "after": None}
            tx_obj = payload.get("transaction") or {}
            tx_id = tx_obj.get("id")
            after = {
                "transaction_id": tx_id,
                "date": date_str,
                "account_id": account_id,
                "amount": amount,
                "merchant_name": merchant_name,
                "category": cat.get("name"),
                "category_id": cat["id"],
                "notes": notes,
            }
            if tx_id:
                try:
                    save_transaction(
                        tx_id=tx_id,
                        account_id=account_id,
                        amount=amount,
                        date=date_str,
                        merchant_name=merchant_name,
                        category=cat.get("name"),
                        notes=notes,
                        pending=False,
                        source="monarch",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Monarch create succeeded but local write failed: %s", exc)
            return {
                "status": "success" if tx_id else "failed",
                "transaction_id": tx_id,
                "before": before,
                "after": after,
                "monarch_response": res,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)}

    async def delete_transaction(self, transaction_id: str) -> dict[str, Any]:
        """Delete a transaction from Monarch Money and the local store."""
        try:
            client = await self._authenticate()
        except MonarchAuthError as exc:
            return self._auth_failure(exc)
        before = get_transaction(transaction_id)
        if not before:
            return {"status": "failed", "error": f"Transaction '{transaction_id}' not found locally."}
        try:
            res = await client.delete_transaction(transaction_id=transaction_id)
            err = _graphql_errors(res) if isinstance(res, dict) else None
            if err:
                return {"status": "failed", "error": err, "before": before, "after": None}
            # Remove from local DB
            with get_db() as conn:
                conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
                conn.commit()
            return {
                "status": "success",
                "deleted_transaction_id": transaction_id,
                "before": before,
                "after": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc), "before": before}

    # ── full sync ────────────────────────────────────────────────────

    async def _fetch_all_transactions(
        self, client, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            batch = await client.get_transactions(
                limit=PAGE_SIZE,
                offset=page * PAGE_SIZE,
                start_date=start_date,
                end_date=end_date,
            )
            results = (batch or {}).get("allTransactions", {}).get("results", []) or []
            collected.extend(results)
            if len(results) < PAGE_SIZE:
                break
        return collected

    async def sync_now(self, days: int = DEFAULT_SYNC_DAYS, client=None) -> dict[str, Any]:
        if self.is_syncing:
            return {"status": "in_progress", "message": "A sync is already running."}

        self.is_syncing = True
        try:
            try:
                client = client or await self._authenticate()
            except MonarchAuthError as exc:
                result = self._auth_failure(exc)
                result["local_data_is_demo"] = get_sync_state()["is_demo"]
                result["last_successful_sync"] = get_sync_state()["last_sync_at"]
                return result

            end = date.today()
            start = end - timedelta(days=max(1, days))
            try:
                accounts = (await client.get_accounts() or {}).get("accounts", []) or []
                transactions = await self._fetch_all_transactions(
                    client, start.isoformat(), end.isoformat()
                )
                await self.get_categories(sync_to_db=True, client=client)
                await self.get_budgets(sync_to_db=True, client=client)
                await self.get_recurring_transactions(sync_to_db=True, client=client)
            except Exception as exc:  # noqa: BLE001
                msg = f"Monarch fetch failed: {type(exc).__name__}: {exc}"
                set_sync_state(status="fetch_failed", error=msg)
                state = get_sync_state()
                return {
                    "status": "fetch_failed",
                    "message": msg,
                    "synced": False,
                    "local_data_is_demo": state["is_demo"],
                    "last_successful_sync": state["last_sync_at"],
                }

            purged = purge_demo_data()
            written_accounts = self._write_accounts(accounts)
            written_tx = self._write_transactions(transactions)

            set_sync_state(
                source="monarch",
                status="success",
                error=None,
                accounts=written_accounts,
                transactions=written_tx,
                stamp_time=True,
            )
            return {
                "status": "success",
                "synced": True,
                "synced_accounts": written_accounts,
                "synced_transactions": written_tx,
                "window": {"start": start.isoformat(), "end": end.isoformat()},
                "demo_rows_removed": purged,
                "local_data_is_demo": False,
            }
        finally:
            self.is_syncing = False

    @staticmethod
    def _write_accounts(accounts: list[dict[str, Any]]) -> int:
        written = 0
        with get_db() as conn:
            cur = conn.cursor()
            for acc in accounts:
                try:
                    acc_type = normalize_account_type(acc.get("type"))
                    cur.execute(
                        """
                        INSERT INTO accounts
                            (id, name, type, subtype, current_balance, source, updated_at)
                        VALUES (?, ?, ?, ?, ?, 'monarch', CURRENT_TIMESTAMP)
                        ON CONFLICT(id) DO UPDATE SET
                            name=excluded.name,
                            type=excluded.type,
                            subtype=excluded.subtype,
                            current_balance=excluded.current_balance,
                            source='monarch',
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (
                            acc.get("id"),
                            acc.get("displayName") or acc.get("name") or "Unnamed account",
                            acc_type,
                            (acc.get("subtype") or {}).get("name")
                            if isinstance(acc.get("subtype"), dict)
                            else acc.get("subtype"),
                            float(acc.get("currentBalance") or 0.0),
                        ),
                    )
                    written += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipped account %s: %s", acc.get("id"), exc)
            conn.commit()
        return written

    @staticmethod
    def _write_transactions(transactions: list[dict[str, Any]]) -> int:
        written = 0
        with get_db() as conn:
            cur = conn.cursor()
            for tx in transactions:
                try:
                    cur.execute(
                        """
                        INSERT INTO transactions
                            (id, account_id, amount, date, merchant_name, category,
                             notes, pending, source, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'monarch', CURRENT_TIMESTAMP)
                        ON CONFLICT(id) DO UPDATE SET
                            amount=excluded.amount,
                            date=excluded.date,
                            merchant_name=excluded.merchant_name,
                            category=excluded.category,
                            notes=excluded.notes,
                            pending=excluded.pending,
                            source='monarch',
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (
                            tx.get("id"),
                            (tx.get("account") or {}).get("id"),
                            float(tx.get("amount") or 0.0),
                            tx.get("date"),
                            (tx.get("merchant") or {}).get("name") or "Unknown",
                            (tx.get("category") or {}).get("name") or "Uncategorized",
                            tx.get("notes") or "",
                            1 if tx.get("pending") else 0,
                        ),
                    )
                    written += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipped transaction %s: %s", tx.get("id"), exc)
            conn.commit()
        return written


def sync_now_sync(days: int = DEFAULT_SYNC_DAYS) -> dict[str, Any]:
    from .runtime import run_async

    return run_async(lambda: MonarchSyncService().sync_now(days=days))
