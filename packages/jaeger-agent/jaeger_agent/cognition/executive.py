"""Turn executive — bind a durable run around one agent turn.

Not a second SI. The loop still talks; this module owns run identity,
heartbeat, and a checkpoint of where the turn stopped. An LLM does not
decide those.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from jaeger_agent.cognition.commitments import CommitmentStore
from jaeger_agent.cognition.intake import ClaimWriter, extract_told_propositions, record_told
from jaeger_agent.cognition.planner import EvidenceFirstPlanner, Planner
from jaeger_agent.cognition.runs import Run, RunStore
from jaeger_agent.memory.models import BeliefStatus, Claim, ProvenanceKind


TURN_LOOP_KIND = "turn-loop"


@runtime_checkable
class Loop(Protocol):
    """The slice of JaegerAgent the executive needs. Avoids an import cycle."""

    run_id: str | None
    last_halt_reason: str | None
    last_iteration_count: int
    primary_adapter: Any

    def bind_run(self, run_id: str | None) -> None: ...

    def run_turn(self, text: str, *, content: Any = None) -> str: ...


class TurnExecutive:
    """Compose run store + agent for one conversational turn."""

    def __init__(
        self,
        agent: Loop,
        runs: RunStore,
        commitments: CommitmentStore,
        *,
        provider: str | None = None,
        claims: ClaimWriter | None = None,
        planner: Planner | None = None,
        world_event=None,
        prepare_world_context: bool = True,
        durable_task: bool = False,
    ) -> None:
        self.durable_task = durable_task
        self.agent = agent
        self.runs = runs
        self.commitments = commitments
        self.claims = claims
        self.world_event = world_event
        self.prepare_world_context = prepare_world_context
        self.planner = planner or EvidenceFirstPlanner()
        self.provider = provider or getattr(agent.primary_adapter, "name", None)
        binder = getattr(agent, "set_effect_checkpoint", None)
        self._bind_checkpoint = binder if callable(binder) else None

    def ensure_run(self) -> Run:
        if self.agent.run_id:
            existing = self.runs.get(self.agent.run_id)
            if existing is not None:
                if existing.state == "created":
                    existing = self.runs.transition(existing.id, "active")
                elif existing.state == "recoverable" or (
                    existing.state == "blocked" and existing.reason == "owner_lost"
                ):
                    pending = self._pending_effects(existing.id)
                    if not pending:
                        existing, _checkpoint = self.runs.resume(
                            existing.id, owner_pid=os.getpid(),
                        )
                    else:
                        return existing
                elif existing.state == "completed":
                    existing = None
                if existing is not None:
                    self.runs.heartbeat(existing.id, owner_pid=os.getpid())
                    return existing
        open_commitments = [
            item for item in self.commitments.list()
            if item.kind == TURN_LOOP_KIND and item.state in {"created", "active"}
        ]
        if open_commitments:
            commitment = open_commitments[0]
            if commitment.state == "created":
                commitment = self.commitments.transition(commitment.id, "active")
        else:
            commitment = self.commitments.create(TURN_LOOP_KIND, kind=TURN_LOOP_KIND)
            commitment = self.commitments.transition(commitment.id, "active")
        # An unbound turn is a new request and gets its own run. Adopting
        # some other active or orphaned run here put unrelated requests —
        # from other sessions and other processes — under one run id, and
        # effect keys are scoped by run id, so a later request's identical
        # write could be skipped as "already done". Continuing a specific
        # run is the caller's decision: it binds that run first.
        run = self.runs.create(
            commitment.id, provider=self.provider, owner_pid=os.getpid(),
        )
        run = self.runs.transition(run.id, "active")
        self.agent.bind_run(run.id)
        return run

    @staticmethod
    def _pending_effects(run_id: str) -> list[Any]:
        try:
            from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
            return [
                e for e in SqliteEffectLedger().list(status="pending")
                if e.run_id == run_id
            ]
        except Exception:
            return []

    def run_turn(self, text: str, *, content: Any = None) -> str:
        run = self.ensure_run()
        if run.state == "blocked":
            if run.reason == "turn_failed":
                raise RuntimeError(f"Run {run.id} is permanently BLOCKED ({run.reason}).")
            return (
                f"Run {run.id} is BLOCKED ({run.reason or 'indeterminate effect'}). "
                "Not retrying an indeterminate external effect."
            )
        if self._bind_checkpoint is not None:
            self._bind_checkpoint(
                lambda name, args, message: self._checkpoint_tool_result(
                    run.id, name, args, message,
                )
            )
        needs_evidence = False
        if self.claims is not None and self.world_event is not None:
            from jaeger_agent.cognition.world import WorldModel
            world = WorldModel(self.claims)
            context = world.prepare(self.world_event)
            if self.prepare_world_context:
                if context:
                    text = context + "\n\n" + text
                    if isinstance(content, list):
                        content = [{"type": "text", "text": context}, *content]
                    elif isinstance(content, str):
                        content = context + "\n\n" + content
        elif self.claims is not None:
            asserted = extract_told_propositions(text)
            record_told(self.claims, text, source_id=run.id)
            rebuilder = getattr(self.claims, "rebuild_beliefs_from_claims", None)
            if callable(rebuilder):
                beliefs = rebuilder(subject="user")
                asserted_keys = {(subject, predicate) for subject, predicate, _ in asserted}
                needs_evidence = bool(asserted_keys) and self.planner.next_action(
                    contradicted=any(
                        b.status == BeliefStatus.CONTRADICTED
                        and (b.subject, b.predicate) in asserted_keys
                        for b in beliefs
                    ),
                ) in {"gather_evidence", "ask_user"}
        if needs_evidence:
            result = "I have conflicting information about that. Which value should I treat as current?"
            self.runs.checkpoint(run.id, {"halt": "needs_evidence", "iterations": 0})
            return result
        try:
            result = (self.agent.run_turn(text) if content is None
                      else self.agent.run_turn(text, content=content))
        except Exception:
            self.runs.transition(run.id, "blocked", reason="turn_failed")
            raise
        cursor: dict[str, Any] = {
            "halt": self.agent.last_halt_reason,
            "iterations": self.agent.last_iteration_count,
            "messages": list(getattr(self.agent, "messages", [])),
        }
        self.runs.checkpoint(run.id, cursor)
        if not self.agent.last_halt_reason and not self.durable_task:
            try:
                self.runs.transition(run.id, "completed")
            except Exception:
                pass
        elif self.agent.last_halt_reason == "interrupted":
            # The turn was stopped, not finished. Close the run so it is not
            # left "active" forever: cancelled when every claimed effect has
            # an outcome (completed effects stay recorded in the ledger), or
            # interrupted — non-terminal, reconcilable — when one is pending.
            state = "interrupted" if self._pending_effects(run.id) else "cancelled"
            try:
                self.runs.transition(run.id, state, reason="interrupted")
            except Exception:
                pass
        if self.claims is not None:
            self.claims.add_claim(Claim.create(
                subject="agent", predicate="responded", value=result[:2000],
                provenance=ProvenanceKind.SYSTEM, source_id=run.id,
            ))
        return result

    def _checkpoint_tool_result(
        self, run_id: str, name: str, args: dict[str, Any], message: dict[str, Any],
    ) -> None:
        messages = list(getattr(self.agent, "messages", []))
        if not messages or messages[-1] != message:
            messages.append(dict(message))
        self.runs.checkpoint(run_id, {
            "event": "tool_result", "tool": name, "args": dict(args or {}),
            "message": dict(message),
            "messages": messages,
        })
        if self.claims is not None:
            self.claims.add_claim(Claim.create(
                subject="agent", predicate="tool_result", value=str(message.get("content", ""))[:2000],
                provenance=ProvenanceKind.OBSERVED, source_id=run_id,
                metadata={"tool": name},
            ))


__all__ = ["Loop", "TURN_LOOP_KIND", "TurnExecutive"]
