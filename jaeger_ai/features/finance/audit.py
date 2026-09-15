"""Cryptographically verifiable, append-only audit trail."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from .store import FinanceStore

logger = logging.getLogger("jaeger_ai.features.finance.audit")


class AuditLog:
    """Provides high-level audit logging and chain-integrity verification."""

    def __init__(self, store: FinanceStore) -> None:
        self.store = store

    def log(self, action: str, actor: str, details: dict[str, Any]) -> str:
        """Record an immutable audit entry."""
        return self.store.append_audit(action, actor, details)

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent audit entries."""
        return self.store.get_audit_log(limit=limit)

    def verify_integrity(self) -> dict[str, Any]:
        """Verify the cryptographic hash-chain across all recorded audit entries."""
        entries = self.store.get_audit_log(limit=1000)
        # Reverse to chronological order for verification
        chronological = list(reversed(entries))

        if not chronological:
            return {"ok": True, "entries_checked": 0, "verified": True}

        expected_prev = "0" * 64
        for i, entry in enumerate(chronological):
            if entry["prev_hash"] != expected_prev:
                return {
                    "ok": False,
                    "verified": False,
                    "error": f"Chain broken at entry ID {entry['id']}: expected prev_hash {expected_prev}, got {entry['prev_hash']}",
                }

            # Recalculate hash
            details_str = json.dumps(entry["details"], sort_keys=True, default=str)
            h = hashlib.sha256()
            h.update(f"{entry['prev_hash']}:{entry['timestamp']}:{entry['action']}:{entry['actor']}:{details_str}".encode())
            computed_hash = h.hexdigest()

            if computed_hash != entry["record_hash"]:
                return {
                    "ok": False,
                    "verified": False,
                    "error": f"Record hash mismatch at entry ID {entry['id']}: computed {computed_hash}, got {entry['record_hash']}",
                }

            expected_prev = entry["record_hash"]

        return {
            "ok": True,
            "entries_checked": len(chronological),
            "verified": True,
            "last_record_hash": expected_prev,
        }
