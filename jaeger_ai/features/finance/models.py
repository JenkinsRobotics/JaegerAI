"""Domain models and value objects for the Jaeger Finance Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any


class AccountType(str, Enum):
    DEPOSITORY = "depository"  # Checking, savings
    CREDIT = "credit"          # Credit cards
    LOAN = "loan"              # Mortgages, student loans, auto loans
    INVESTMENT = "investment"  # Brokerage, retirement
    OTHER = "other"

    @classmethod
    def from_str(cls, val: str | None) -> AccountType:
        if not val:
            return cls.OTHER
        v = val.lower()
        if any(x in v for x in ("checking", "savings", "depository", "cash")):
            return cls.DEPOSITORY
        if "credit" in v:
            return cls.CREDIT
        if any(x in v for x in ("loan", "mortgage", "debt")):
            return cls.LOAN
        if any(x in v for x in ("invest", "brokerage", "401k", "ira")):
            return cls.INVESTMENT
        return cls.OTHER


class ReviewStatus(str, Enum):
    NEW = "new"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ApprovalTier(str, Enum):
    AUTONOMOUS = "autonomous"            # Read, calc, summary, pacing, exact approved rule
    ONE_CLICK = "one_click"              # New merchant, budget override, rule update
    EXPLICIT_CONFIRM = "explicit_confirm"# Disconnect, data deletion, export
    BLOCKED = "blocked"                  # Money movement (disabled by doctrine)


@dataclass
class Account:
    id: str
    name: str
    type: AccountType
    balance: float
    currency: str = "USD"
    mask: str | None = None  # Last 4 digits only
    subtype: str | None = None
    is_hidden: bool = False
    updated_at: str | None = None
    provider: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "balance": round(self.balance, 2),
            "currency": self.currency,
            "mask": self.mask,
            "subtype": self.subtype,
            "is_hidden": self.is_hidden,
            "updated_at": self.updated_at,
            "provider": self.provider,
        }


@dataclass
class Transaction:
    id: str
    account_id: str
    date: str  # YYYY-MM-DD
    amount: float  # Positive = outflow/expense, Negative = inflow/income (Monarch standard) or vice-versa
    merchant: str
    raw_statement: str
    category: str = "Uncategorized"
    category_id: str | None = None
    pending: bool = False
    is_split: bool = False
    parent_id: str | None = None
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    is_transfer: bool = False
    review_status: ReviewStatus = ReviewStatus.NEW
    suggested_category: str | None = None
    classification_confidence: float = 0.0
    classification_explanation: str = ""
    matching_rule_id: str | None = None
    account_name: str = ""
    provider: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "date": self.date,
            "amount": round(self.amount, 2),
            "merchant": self.merchant,
            "raw_statement": self.raw_statement,
            "category": self.category,
            "category_id": self.category_id,
            "pending": self.pending,
            "is_split": self.is_split,
            "parent_id": self.parent_id,
            "notes": self.notes,
            "tags": list(self.tags),
            "is_transfer": self.is_transfer,
            "review_status": self.review_status.value,
            "suggested_category": self.suggested_category,
            "classification_confidence": round(self.classification_confidence, 2),
            "classification_explanation": self.classification_explanation,
            "matching_rule_id": self.matching_rule_id,
            "provider": self.provider,
        }


@dataclass
class Category:
    id: str
    name: str
    group_name: str = "General"
    is_income: bool = False
    is_system: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "group_name": self.group_name,
            "is_income": self.is_income,
            "is_system": self.is_system,
        }


@dataclass
class CategoryBudget:
    category: str
    budgeted: float
    actual: float
    remaining: float
    spent_pct: float = 0.0
    category_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "budgeted": round(self.budgeted, 2),
            "actual": round(self.actual, 2),
            "remaining": round(self.remaining, 2),
            "spent_pct": round(self.spent_pct, 1),
            "category_id": self.category_id,
        }


@dataclass
class Rule:
    id: str
    name: str
    pattern: str  # substring or regex
    target_category: str
    target_tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "user"  # "user", "monarch", "historical", "recurring"
    approved_by_user: bool = True
    scope: str = "all_accounts"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_used_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "pattern": self.pattern,
            "target_category": self.target_category,
            "target_tags": list(self.target_tags),
            "confidence": round(self.confidence, 2),
            "source": self.source,
            "approved_by_user": self.approved_by_user,
            "scope": self.scope,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }


@dataclass
class PendingAction:
    id: str
    action_type: str
    payload: dict[str, Any]
    rationale: str
    tier: ApprovalTier
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None
    status: str = "pending"  # "pending", "approved", "rejected", "executed", "expired"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "payload": self.payload,
            "rationale": self.rationale,
            "tier": self.tier.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
        }


@dataclass
class SyncSummary:
    ok: bool
    provider: str
    accounts_synced: int = 0
    transactions_synced: int = 0
    duplicates_skipped: int = 0
    budgets_synced: int = 0
    synced_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "accounts_synced": self.accounts_synced,
            "transactions_synced": self.transactions_synced,
            "duplicates_skipped": self.duplicates_skipped,
            "budgets_synced": self.budgets_synced,
            "synced_at": self.synced_at,
            "error": self.error,
        }
