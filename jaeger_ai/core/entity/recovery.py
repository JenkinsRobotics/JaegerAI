"""Resident boot recovery using CommitmentStore / RunStore / EffectLedger."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

logger = logging.getLogger("jaeger.entity.recovery")


@dataclass
class RecoveryReport:
    blocked_runs: list[str]
    pending_effects: list[str]
    resumed: list[str]
    errors: list[str]
    # Owner died, no half-done effect: safe to continue once a caller binds it.
    recoverable: list[str] = field(default_factory=list)


class RecoveryManager:
    """Scan nonterminal runs at OWNER boot. Never auto-retry indeterminate effects."""

    def scan_resumable_runs(self) -> RecoveryReport:
        report = RecoveryReport(blocked_runs=[], pending_effects=[], resumed=[], errors=[])
        try:
            from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
            from jaeger_agent.cognition.effects import EffectIndeterminate
            import os
        except Exception as exc:
            report.errors.append(f"durable cognition unavailable: {exc}")
            return report

        try:
            store = SqliteRunStore()
            newly = store.recover()
            existing = [
                r for r in store.list(state="blocked")
                if r.reason == "owner_lost"
            ]
            blocked_by_id = {r.id: r for r in newly}
            for run in existing:
                blocked_by_id.setdefault(run.id, run)
            ledger = SqliteEffectLedger()
            pending = {e.key: e for e in ledger.list(status="pending")}
            for effect in pending.values():
                report.pending_effects.append(effect.key)
            for run in blocked_by_id.values():
                report.blocked_runs.append(run.id)
                run_pending = [
                    key for key, eff in pending.items()
                    if eff.run_id == run.id
                ]
                if run_pending:
                    # Crash mid-effect: do not resume and do not replay.
                    logger.warning(
                        "Run %s stays BLOCKED; indeterminate effects %s",
                        run.id, run_pending,
                    )
                    continue
                try:
                    # Mark it resumable; do not claim it. Relabelling it
                    # ``active`` under this pid with nothing executing it left
                    # hundreds of runs "active" forever and handed them to
                    # unrelated requests. Whoever re-dispatches the request
                    # binds the run and resumes it, so the run-scoped effect
                    # ledger skips work that already completed.
                    recoverable = store.transition(run.id, "recoverable", reason="owner_lost")
                    checkpoint = store.latest_checkpoint(run.id)
                    report.recoverable.append(recoverable.id)
                    logger.info(
                        "Run %s is recoverable from checkpoint seq=%s",
                        recoverable.id,
                        getattr(checkpoint, "seq", None),
                    )
                    try:
                        from jaeger_ai.core.entity.events import EventType, JaegerEvent
                        from jaeger_ai.core.entity.runtime import EntityRuntime
                        rt = EntityRuntime.get_singleton()
                        rt.event_store.append(
                            JaegerEvent.typed(
                                EventType.LEARNING_UPDATED.value
                                if not hasattr(EventType, "RUN_RESUMED")
                                else EventType.LEARNING_UPDATED.value,
                                {
                                    "run_id": recoverable.id,
                                    "reason": "owner_lost_recoverable",
                                    "checkpoint": getattr(checkpoint, "cursor", None),
                                    "effect_keys_done": True,
                                },
                                actor="system:recovery",
                                source="recovery_manager",
                            )
                        )
                    except Exception:
                        pass
                except Exception as exc:
                    report.errors.append(f"resume {run.id}: {exc}")
            EffectIndeterminate  # imported for type presence
        except Exception as exc:
            report.errors.append(f"run recover: {exc}")

        logger.info(
            "Recovery scan blocked_runs=%s recoverable=%s pending_effects=%s errors=%s",
            len(report.blocked_runs),
            len(report.recoverable),
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
