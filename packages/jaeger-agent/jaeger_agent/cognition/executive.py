"""Turn executive — bind a durable run around one agent turn.

Not a second SI. The loop still talks; this module owns run identity,
heartbeat, and a checkpoint of where the turn stopped. An LLM does not
decide those.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from jaeger_agent.cognition.commitments import CommitmentStore
from jaeger_agent.cognition.intake import ClaimWriter, record_told
from jaeger_agent.cognition.runs import Run, RunStore


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
    ) -> None:
        self.agent = agent
        self.runs = runs
        self.commitments = commitments
        self.claims = claims
        self.provider = provider or getattr(agent.primary_adapter, "name", None)

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
        if self.claims is not None:
            record_told(self.claims, text, source_id=run.id)
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
        return result


__all__ = ["Loop", "TURN_LOOP_KIND", "TurnExecutive"]
