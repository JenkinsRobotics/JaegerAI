"""Explicit, durable financial memory and rule management."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from .models import Rule
from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.memory")


class FinanceMemory:
    """Manages explicit, operator-approved financial rules and preferences."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store

    def add_rule(
        self,
        name: str,
        pattern: str,
        target_category: str,
        target_tags: list[str] | None = None,
        scope: str = "all_accounts",
        source: str = "user",
        approved_by_user: bool = True,
        confidence: float = 1.0,
    ) -> Rule:
        """Create and persist a new explicit rule."""
        rule_id = f"rule_{uuid.uuid4().hex[:12]}"
        rule = Rule(
            id=rule_id,
            name=name,
            pattern=pattern,
            target_category=target_category,
            target_tags=target_tags or [],
            scope=scope,
            source=source,
            approved_by_user=approved_by_user,
            confidence=confidence,
            created_at=datetime.now(UTC).isoformat(),
        )
        self.store.upsert_rule(rule)
        self.store.append_audit("rule_created", "operator", rule.to_dict())
        return rule

    def list_rules(self) -> list[Rule]:
        """Return all stored financial rules."""
        return self.store.get_rules()

    def remove_rule(self, rule_id: str) -> bool:
        """Delete an explicit rule by ID."""
        success = self.store.delete_rule(rule_id)
        if success:
            self.store.append_audit("rule_deleted", "operator", {"rule_id": rule_id})
        return success

    def record_rule_usage(self, rule_id: str) -> None:
        """Update last_used_at timestamp when a rule is matched."""
        rules = self.store.get_rules()
        for r in rules:
            if r.id == rule_id:
                r.last_used_at = datetime.now(UTC).isoformat()
                self.store.upsert_rule(r)
                break
