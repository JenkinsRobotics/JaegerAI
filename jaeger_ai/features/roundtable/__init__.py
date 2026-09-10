"""Jaeger Roundtable feature package.

Provides multi-agent debate, consensus building, and turn-taking orchestration
between Jaeger, Hermes, and OpenClaw.
"""

from .service import TableService, member_session
from .policy import MEMBERS, MODES, COLLABORATION_TASKS, plan, chair_for, decide, registry
from .progress import Progress, budgets

__all__ = [
    "TableService",
    "member_session",
    "MEMBERS",
    "MODES",
    "COLLABORATION_TASKS",
    "plan",
    "chair_for",
    "decide",
    "registry",
    "Progress",
    "budgets",
]
