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

    def run_turn(self, text: str) -> str: ...


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
    ) -> None:
        self.agent = agent
        self.runs = runs
        self.commitments = commitments
        self.claims = claims
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
                self.runs.heartbeat(existing.id, owner_pid=os.getpid())
                return existing
        open_commitments = [
            item for item in self.commitments.list(state="active")
            if item.kind == TURN_LOOP_KIND
        ]
        commitment = open_commitments[0] if open_commitments else self.commitments.create(
            TURN_LOOP_KIND, kind=TURN_LOOP_KIND,
        )
        active = self.runs.list(commitment_id=commitment.id, state="active")
        if active:
            run = active[0]
            self.runs.heartbeat(run.id, owner_pid=os.getpid())
            self.agent.bind_run(run.id)
            return run
        run = self.runs.create(
            commitment.id, provider=self.provider, owner_pid=os.getpid(),
        )
        run = self.runs.transition(run.id, "active")
        self.agent.bind_run(run.id)
        return run

    def run_turn(self, text: str) -> str:
        run = self.ensure_run()
        if self._bind_checkpoint is not None:
            self._bind_checkpoint(
                lambda name, args, message: self._checkpoint_tool_result(
                    run.id, name, args, message,
                )
            )
        needs_evidence = False
        if self.claims is not None:
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
            result = self.agent.run_turn(text)
        except Exception:
            self.runs.transition(run.id, "blocked", reason="turn_failed")
            raise
        cursor: dict[str, Any] = {
            "halt": self.agent.last_halt_reason,
            "iterations": self.agent.last_iteration_count,
        }
        self.runs.checkpoint(run.id, cursor)
        if self.claims is not None:
            self.claims.add_claim(Claim.create(
                subject="agent", predicate="responded", value=result[:2000],
                provenance=ProvenanceKind.SYSTEM, source_id=run.id,
            ))
        return result

    def _checkpoint_tool_result(
        self, run_id: str, name: str, args: dict[str, Any], message: dict[str, Any],
    ) -> None:
        self.runs.checkpoint(run_id, {
            "event": "tool_result", "tool": name, "args": dict(args or {}),
            "message": dict(message),
        })
        if self.claims is not None:
            self.claims.add_claim(Claim.create(
                subject="agent", predicate="tool_result", value=str(message.get("content", ""))[:2000],
                provenance=ProvenanceKind.OBSERVED, source_id=run_id,
                metadata={"tool": name},
            ))


__all__ = ["Loop", "TURN_LOOP_KIND", "TurnExecutive"]
