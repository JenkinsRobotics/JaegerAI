"""Persistent step controller — OpenHands / Hermes outer loop.

Request-response chat models stop when they emit prose. That is the
correct inner-turn rule (``drive_one_turn`` exits on no tool calls).
It is the wrong *job* rule. OpenHands' ``AgentController._step`` and
Hermes' conversation loop keep a state machine in charge:

    INIT → RUNNING ⇄ (compact, steer, step) → COMPLETED
                                         ↘ AWAITING_APPROVAL
                                         ↘ FAILED

The inner turn stays Jaeger's existing loop. This module is the outer
engine that decides whether that turn was a *batch*, not an *answer*.

Terminal actions are observable, never declared:

  * ``complete_task`` with a finished ledger → COMPLETED
  * a question / blocker → AWAITING_APPROVAL
  * an error, a ``/stop``, or a spent step budget → FAILED

A prose "all done" on an open ledger is **not** terminal — that is the
failure the donor loops exist to prevent.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable

from jaeger_ai.core.runtime import continuation, execution
from jaeger_ai.core.runtime.autonomous_runner import (
    WORKER_PREAMBLE,
    harness_prompt,
    looks_like_batch,
    next_continuation_prompt,
)
from jaeger_ai.core.runtime.context_compactor import compact_agent
from jaeger_ai.core.runtime.work_ledger import (
    active_ledger,
    consume_completion,
    last_completion,
)


TurnFn = Callable[..., dict[str, Any]]
ProgressFn = Callable[[dict[str, Any]], None]


class AgentState(str, Enum):
    INIT = "INIT"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JaegerAgentController:
    """Donor-shaped continuous step-loop controller.

    ``_step`` is one inner turn. ``run_to_completion`` is the while-loop
    that OpenHands keeps on the controller, not on the model.
    """

    def __init__(
        self,
        client: Any,
        max_steps: int = 100,
        *,
        turn_fn: TurnFn | None = None,
        isolated: bool = True,
        batch: bool = False,
        on_progress: ProgressFn | None = None,
        on_step: ProgressFn | None = None,
        allow_persona: bool = False,
        agent: Any = None,
    ) -> None:
        self.client = client
        self.max_steps = max(1, int(max_steps or execution.max_steps()))
        self.turn_fn = turn_fn
        self.isolated = isolated
        self.batch = batch
        self.on_progress = on_progress
        self.on_step = on_step
        self.allow_persona = allow_persona
        self.agent = agent
        self.state = AgentState.INIT
        self.step_count = 0
        self.reason = ""
        self._started = 0.0
        self._activity: list[Any] = []
        self._last: dict[str, Any] = {}

    def _turn(self) -> TurnFn:
        if self.turn_fn is not None:
            return self.turn_fn
        from jaeger_ai.main import _run_turn
        return _run_turn

    def _step(self, prompt: str, session_key: str) -> dict[str, Any]:
        """One inner turn — OpenHands ``_step`` / Hermes one iteration."""
        if self.on_step is not None:
            try:
                ledger = active_ledger()
                self.on_step({
                    "step": self.step_count,
                    "prompt": prompt,
                    "state": self.state.value,
                    "ledger": None if ledger is None else ledger.as_dict(),
                })
            except Exception:  # noqa: BLE001
                pass
        out = self._turn()(
            self.client, prompt,
            session_key=session_key,
            allow_persona=self.allow_persona,
        )
        self.step_count += 1
        self._activity.extend(out.get("tool_activity") or [])
        packed = dict(out)
        packed["autonomous"] = True
        packed["steps"] = self.step_count
        packed["tool_activity"] = list(self._activity)
        packed["elapsed_s"] = time.perf_counter() - self._started
        packed["state"] = self.state.value
        if self.on_progress is not None:
            try:
                ledger = active_ledger()
                self.on_progress({
                    "step": self.step_count,
                    "text": packed.get("text") or "",
                    "error": packed.get("error"),
                    "tool_activity": out.get("tool_activity") or [],
                    "state": self.state.value,
                    "ledger": None if ledger is None else ledger.as_dict(),
                    "completion": last_completion(),
                })
            except Exception:  # noqa: BLE001
                pass
        self._last = packed
        return packed

    def _has_terminal_action(self, last: dict[str, Any]) -> bool:
        """True when the controller — not the model's prose — should stop."""
        if last.get("error"):
            return True
        if execution.stop_requested():
            return True
        if last_completion():
            return True
        ledger = active_ledger()
        if ledger is not None and ledger.completed:
            return True
        if continuation.is_loop_breaker(last.get("halt_reason")):
            return True
        # Inner-turn fuse is not a job terminal. The next _step runs.
        if continuation.hit_inner_cap(last.get("halt_reason")):
            return False
        verdict = continuation.classify(last.get("text") or "")
        return verdict in {"question", "blocked"}

    def _terminal_state(self, last: dict[str, Any]) -> AgentState:
        if last.get("error"):
            self.reason = "error"
            return AgentState.FAILED
        if continuation.is_loop_breaker(last.get("halt_reason")):
            self.reason = str(last.get("halt_reason") or "loop_breaker")
            return AgentState.FAILED
        if execution.stop_requested():
            self.reason = "stopped"
            return AgentState.FAILED
        if last_completion() or (
            active_ledger() is not None and active_ledger().completed
        ):
            self.reason = "complete_task"
            return AgentState.COMPLETED
        verdict = continuation.classify(last.get("text") or "")
        if verdict in {"question", "blocked"}:
            self.reason = verdict
            return AgentState.AWAITING_APPROVAL
        self.reason = "settled"
        return AgentState.COMPLETED

    def _compact_context_if_needed(self, session_key: str) -> bool:
        """Claude-Code / Hermes 80% window pass. Never raises."""
        agent = self.agent
        if agent is None:
            try:
                from jaeger_ai.main import _jaeger_agents_by_session
                agent = _jaeger_agents_by_session.get(session_key)
            except Exception:  # noqa: BLE001
                agent = None
        return bool(compact_agent(agent))

    def _build_continuation_prompt(self, last: dict[str, Any]) -> str | None:
        remaining = max(0, self.max_steps - self.step_count)
        nxt = next_continuation_prompt(
            last.get("text") or "",
            tool_activity=last.get("tool_activity") or [],
            isolated=self.isolated,
            batch=self.batch,
            steps_left=remaining,
            objective=self.objective,
            halt_reason=last.get("halt_reason"),
        )
        if nxt:
            return nxt
        # Batch jobs with an open ledger keep going even if the
        # classifier called the last reply "settled" / "complete".
        ledger = active_ledger()
        if (self.batch or (ledger is not None and not ledger.completed)) \
                and remaining > 0 and not execution.stop_requested():
            return harness_prompt(ledger, objective=self.objective)
        return None

    def run_to_completion(
        self,
        goal: str,
        session_key: str,
        *,
        objective: str = "",
    ) -> dict[str, Any]:
        """Drive ``_step`` until a terminal action, a human gate, or budget."""
        self._started = time.perf_counter()
        self.state = AgentState.RUNNING
        self.step_count = 0
        self.reason = ""
        self._activity = []
        self.objective = (objective or goal or "").strip()
        self.batch = self.batch or looks_like_batch(goal)
        consume_completion()

        if not self.isolated:
            if not execution.run_active():
                execution.begin_run(self.objective, budget=self.max_steps)
            else:
                execution._state["budget"] = self.max_steps  # noqa: SLF001

        prompt = goal
        if self.isolated and self.batch and WORKER_PREAMBLE not in (goal or ""):
            prompt = f"{WORKER_PREAMBLE}\n\n{goal}"

        last = self._step(prompt, session_key)
        while self.state is AgentState.RUNNING:
            if self._has_terminal_action(last):
                self.state = self._terminal_state(last)
                break
            if self.step_count >= self.max_steps:
                self.state = AgentState.FAILED
                self.reason = "budget exhausted"
                break
            if execution.stop_requested():
                self.state = AgentState.FAILED
                self.reason = "stopped"
                break
            self._compact_context_if_needed(session_key)
            steer = self._build_continuation_prompt(last)
            if not steer:
                self.state = AgentState.COMPLETED
                self.reason = "settled"
                break
            last = self._step(steer, session_key)

        if not self.isolated:
            if self.state is AgentState.COMPLETED:
                execution.end_run(self.reason or "complete_task")
            elif self.state is AgentState.FAILED:
                execution.end_run(self.reason or "failed")
            elif self.state is AgentState.AWAITING_APPROVAL:
                execution.end_run(self.reason or "question")
            if self.reason == "stopped":
                execution.clear_stop()

        done = last_completion()
        output = dict(self._last)
        output["state"] = self.state.value
        output["status"] = self.state.value
        output["halt_reason"] = self.reason
        output["steps"] = self.step_count
        output["elapsed_s"] = time.perf_counter() - self._started
        output["autonomous"] = True
        if done or self.reason == "complete_task":
            summary = str((done or {}).get("summary") or output.get("summary") or "")
            output["summary"] = summary
            if summary:
                output["text"] = summary
            consume_completion()
        else:
            output.setdefault("summary", "")
        return {
            "status": self.state.value,
            "state": self.state,
            "steps": self.step_count,
            "reason": self.reason,
            "output": output,
        }


__all__ = ["AgentState", "JaegerAgentController"]
