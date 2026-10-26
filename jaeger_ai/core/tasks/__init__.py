"""Durable background work and scheduling package.

The unified scheduler (UnifiedScheduler) is the recommended interface for all
scheduling. It combines:
- Cron-style scheduling (legacy CronRunner compatible)
- Durable background tasks (GatewayTaskOwner)
- Kanban board task management
"""
from .owner import GatewayTaskOwner
from .models import (
    DurableTask,
    NotificationPolicy,
    RetryPolicy,
    TaskKind,
    TaskRunRecord,
    TaskState,
)
from .store import SqliteDurableTaskStore
from .unified import UnifiedScheduler, TaskCard, BOARD_COLUMNS
from .migration import migrate_all, migrate_legacy_schedules, migrate_legacy_board, needs_migration

__all__ = [
    "BOARD_COLUMNS",
    "DurableTask",
    "GatewayTaskOwner",
    "NotificationPolicy",
    "RetryPolicy",
    "SqliteDurableTaskStore",
    "TaskCard",
    "TaskKind",
    "TaskRunRecord",
    "TaskState",
    "UnifiedScheduler",
    "migrate_all",
    "migrate_legacy_board",
    "migrate_legacy_schedules",
    "needs_migration",
]
