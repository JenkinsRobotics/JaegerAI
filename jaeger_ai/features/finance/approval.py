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

    def evaluate_operation(self, op_name: str) -> ApprovalTier:
        """Return the required approval tier for an operation."""
        # 1. Blocked: money movement (disabled by doctrine)
        if any(w in op_name.lower() for w in ("transfer_money", "make_payment", "trade", "withdraw", "deposit")):
            return ApprovalTier.BLOCKED

        # 2. Explicit confirmation required
        if any(w in op_name.lower() for w in ("disconnect_account", "purge_all", "delete_rule", "export_data")):
            return ApprovalTier.EXPLICIT_CONFIRM

        # 3. One-click review required
        if any(w in op_name.lower() for w in ("categorize_merchant", "modify_budget", "create_rule", "bulk_review")):
            return ApprovalTier.ONE_CLICK

        # 4. Autonomous: reads, calcs, local sync, briefings
        return ApprovalTier.AUTONOMOUS

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

    def approve_action(self, action_id: str) -> dict[str, Any]:
        """Approve a staged action if it has not expired."""
        actions = self.store.get_pending_actions(status="pending")
        matched = next((a for a in actions if a.id == action_id), None)
        if not matched:
            return {"ok": False, "error": f"Pending action '{action_id}' not found or already processed."}

        # Check expiration
        if matched.expires_at:
            now_iso = datetime.now(UTC).isoformat()
            if now_iso > matched.expires_at:
                self.store.update_pending_action_status(action_id, "expired")
                return {"ok": False, "error": f"Pending action '{action_id}' has expired."}

        # In Phase 1: External writes to Monarch are disabled
        self.store.update_pending_action_status(action_id, "approved")
        self.store.append_audit("action_approved", "operator", matched.to_dict())
        return {"ok": True, "action_id": action_id, "status": "approved"}

    def reject_action(self, action_id: str) -> dict[str, Any]:
        """Reject a staged action."""
        success = self.store.update_pending_action_status(action_id, "rejected")
        if success:
            self.store.append_audit("action_rejected", "operator", {"action_id": action_id})
        return {"ok": success, "action_id": action_id, "status": "rejected"}
