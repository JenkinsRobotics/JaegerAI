"""Resident boot recovery using CommitmentStore / RunStore / EffectLedger."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

logger = logging.getLogger("jaeger.entity.recovery")


@dataclass
class RecoveryReport:
    blocked_runs: list[str]
    pending_effects: list[str]
    resumed: list[str]
    errors: list[str]


class RecoveryManager:
    """Scan nonterminal runs at OWNER boot. Never auto-retry indeterminate effects."""

    def scan_resumable_runs(self) -> RecoveryReport:
        report = RecoveryReport(blocked_runs=[], pending_effects=[], resumed=[], errors=[])
        try:
            from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
            from jaeger_agent.cognition.effects import EffectIndeterminate
        except Exception as exc:
            report.errors.append(f"durable cognition unavailable: {exc}")
            return report

        try:
            store = SqliteRunStore()
            blocked = store.recover()
            for run in blocked:
                report.blocked_runs.append(run.id)
        except Exception as exc:
            report.errors.append(f"run recover: {exc}")

        try:
            ledger = SqliteEffectLedger()
            for effect in ledger.list(status="pending"):
                report.pending_effects.append(effect.key)
        except Exception as exc:
            report.errors.append(f"effect scan: {exc}")
            EffectIndeterminate  # imported for type presence

        logger.info(
            "Recovery scan blocked_runs=%s pending_effects=%s errors=%s",
            len(report.blocked_runs),
            len(report.pending_effects),
            report.errors,
        )
        return report

    def effect_is_indeterminate(self, key: str) -> bool:
        try:
            from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
            effect = SqliteEffectLedger().get(key)
            return effect is not None and effect.status == "pending"
        except Exception:
            return False
