"""Boot-time seeding of durable goals from ``operator.toml``.

Reads the operator's ``[[operator.projects]]`` tables and turns each one
into durable project + goal commitments via :meth:`GoalService.seed_from_config`.
Idempotent — safe to call on every boot; already-seeded projects are skipped.

Called once from ``jaeger_ai.main._register_builtins`` right after the goal
tools are imported. Failures are logged and swallowed: a config typo must
never break agent boot.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def seed_operator_goals() -> list[dict[str, Any]]:
    """Seed durable goals from the operator config + the built-in roadmap.

    Seeds two sources, in order:
      1. The built-in JaegerAI production roadmap (``roadmap.roadmap_projects``)
         — the product's own backlog, always seeded.
      2. The operator's ``[[operator.projects]]`` tables — their own goals.

    Idempotent: ``seed_from_config`` skips projects whose ``source_name``
    already exists in the store. Returns all newly created goals.
    """
    try:
        from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
        from jaeger_ai.core.instance.operator_config import load_operator_config

        from .roadmap import roadmap_projects
        from .service import GoalService

        service = GoalService(SqliteCommitmentStore())
        created: list[dict[str, Any]] = []
        # 1. Built-in production roadmap (always).
        created.extend(service.seed_from_config(roadmap_projects()))
        # 2. Operator-declared projects.
        cfg = load_operator_config()
        if cfg.projects:
            created.extend(service.seed_from_config(cfg.projects))
        return created
    except Exception:  # noqa: BLE001 — seeding must never break boot
        logger.exception("goal seeding failed")
        return []


__all__ = ["seed_operator_goals"]
