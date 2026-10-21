"""Approval policy engine enforcing permission boundaries and safety tiers."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import ApprovalTier, PendingAction
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.approval")

DEFAULT_ACTION_TTL_MINUTES = 60


class PolicyViolationError(PermissionError):
    """Raised when an operation violates financial safety policy."""


class ApprovalEngine:
    """Classifies, stages, and enforces approvals according to doctrine."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store

    @staticmethod
    def evaluate_operation(op_name: str) -> ApprovalTier:
        """Closed operation catalog. Unknown names never imply spending authority."""
        from .review import OPERATION_TIERS
        return OPERATION_TIERS.get(op_name, ApprovalTier.BLOCKED) if isinstance(op_name, str) else ApprovalTier.BLOCKED

    def stage_action(
        self,
        action_type: str,
        payload: dict[str, Any],
        rationale: str,
        ttl_minutes: int = DEFAULT_ACTION_TTL_MINUTES,
    ) -> PendingAction:
        """Stage an action requiring operator review into the pending actions store."""
        tier = self.evaluate_operation(action_type)
        if tier == ApprovalTier.BLOCKED:
            raise PolicyViolationError(f"Operation '{action_type}' is strictly prohibited by financial safety doctrine.")

        now = datetime.now(UTC)
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
        action = PendingAction(
            id=f"act_{uuid.uuid4().hex[:12]}",
            action_type=action_type,
            payload=payload,
            rationale=rationale,
            tier=tier,
            created_at=now.isoformat(),
            expires_at=expires_at,
            status="pending",
        )
        self.store.record_pending_action(action)
        self.store.append_audit("action_staged", "system", action.to_dict())
        return action

    def approve_action(self, action_id: str, *, expected_revision=None, operation_id=None) -> dict[str, Any]:
        """Record local review only; no provider write/settlement is performed."""
        from .review import decide
        return decide(self.store, action_id, 'record_review', expected_revision=expected_revision, operation_id=operation_id)

    def reject_action(self, action_id: str, *, expected_revision=None, operation_id=None) -> dict[str, Any]:
        from .review import decide
        return decide(self.store, action_id, 'deny', expected_revision=expected_revision, operation_id=operation_id)
