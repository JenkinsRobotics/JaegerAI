"""Autonomous Personal Finance & Budgeting Feature for JaegerAI."""

from .anomaly import AnomalyDetector
from .approval import ApprovalEngine, PolicyViolationError
from .audit import AuditLog
from .briefing import BriefingEngine
from .budget import BudgetEngine
from .cashflow import CashFlowEngine
from .classifier import TransactionClassifier
from .finance_worker import FinanceWorker
from .memory import FinanceMemory
from .models import (
    Account,
    AccountType,
    ApprovalTier,
    Category,
    CategoryBudget,
    PendingAction,
    ReviewStatus,
    Rule,
    SyncSummary,
    Transaction,
)
from .monarch_service import (
    DEFAULT_SESSION_PATH,
    MonarchAPIError,
    MonarchDateError,
    MonarchError,
    MonarchImportError,
    MonarchService,
    MonarchSessionMissing,
    default_session_path,
    migrate_legacy_session,
    validate_date_bounds,
)
from .provider import FinanceProvider
from .providers.importer import ImportProvider
from .providers.monarch import MonarchProvider
from .security import FinanceCipher, SecuritySanitizer, get_or_create_master_key
from .store import FinanceStore, default_database_path
from .sync import SyncEngine
from .tools import (
    finance_audit,
    finance_briefing,
    finance_inbox,
    finance_summary,
    finance_sync,
    finance_transactions,
)

__all__ = [
    "DEFAULT_SESSION_PATH",
    "Account",
    "AccountType",
    "AnomalyDetector",
    "ApprovalEngine",
    "ApprovalTier",
    "AuditLog",
    "BriefingEngine",
    "BudgetEngine",
    "CashFlowEngine",
    "Category",
    "CategoryBudget",
    "FinanceCipher",
    "FinanceMemory",
    "FinanceProvider",
    "FinanceStore",
    "FinanceWorker",
    "ImportProvider",
    "MonarchAPIError",
    "MonarchDateError",
    "MonarchError",
    "MonarchImportError",
    "MonarchProvider",
    "MonarchService",
    "MonarchSessionMissing",
    "PendingAction",
    "PolicyViolationError",
    "ReviewStatus",
    "Rule",
    "SecuritySanitizer",
    "SyncEngine",
    "SyncSummary",
    "Transaction",
    "TransactionClassifier",
    "default_database_path",
    "default_session_path",
    "finance_audit",
    "finance_briefing",
    "finance_inbox",
    "finance_summary",
    "finance_sync",
    "finance_transactions",
    "get_or_create_master_key",
    "migrate_legacy_session",
    "validate_date_bounds",
]
