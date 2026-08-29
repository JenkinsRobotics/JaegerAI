"""Goal-driven outer loop around a single ``_run_turn``.

The agent loop's exit door is per-turn: a reply with no tool calls is
the final answer. That is the right rule for chat. It is the wrong
rule for "process these 300 items and do not stop until done" — the
model narrates a first batch, the turn ends, and the rest of the list
sits untouched.

This runner is the missing outer loop. It owns control between turns:

  * after each tool-batch turn, if the work ledger is not complete, it
    injects a continuation and fires again;
  * it stops only on a successful ``complete_task``, an explicit human
    approval / blocker gate, a cooperative ``/stop``, or the step budget
    (default: :data:`jaeger_ai.core.runtime.execution.DEFAULT_MAX_STEPS`).

Ordinary ``/auto`` stall-detection (a narrated promise with no ledger)
stays in :mod:`jaeger_ai.core.runtime.continuation` — this module does
not replace it. Surfaces that already loop (the TUI worker) call
:func:`next_continuation_prompt`; the bridge and ``run_command`` call
:class:`AutonomousGoalRunner`.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

from jaeger_ai.core.runtime import continuation, execution
from jaeger_ai.core.runtime.work_ledger import (
    active_ledger,
    last_completion,
)


HARNESS_PREFIX = "[Autonomous Harness]"

# Batch / "keep going" phrasing. Tight on purpose: a casual "do this"
# must not trap the operator in a 100-step loop. Two-digit item counts
# and explicit "until done" / "/goal" are the signals that match the
# jobs this runner exists for.
# Tight on purpose. A false positive starts a 100-step worker loop.
# Counted batches need a process-verb AND a two-digit count; "until
# done" needs an explicit keep-going phrase. Do not widen this without
# adding negatives first.
_BATCH_HINT = re.compile(
    r"(?is)"
    r"(?:do not stop|don't stop|keep going) until "
    r"(?:you(?:'re| are)? )?(?:done|finished|complete|all|every)|"
    r"(?:process(?:ing)?|consolidat(?:e|ing)|go through|work through|"
    r"handle|finish)\b.{0,80}?\b(?:all |every |these )?\d{2,}\s+"
    r"(?:items?|files?|rows?|entries|notes?|folders?|records)\b|"
    r"\bbatch[- ](?:process|job|operation|run)\b|"
    r"(?:audit|organi[sz]e|sync|deduplicat(?:e|ing)|merge|restructur(?:e|ing))"
    r"\b.{0,120}?\b(?:bookmarks?|files|folders|records|entries|notes|"
    r"libraries|collections)\b|"
    r"^/goal\b"
)

_COUNTED_SCOPE = re.compile(
    r"(?i)\b(\d{1,7})\s+(?:items?|files?|rows?|entries|notes?|folders?|records|bookmarks?)\b"
)
_PATH_TOKEN = re.compile(
    r"(?<!https:)(?<!http:)(?:`([^`]+)`|\b([\w./~-]+\.(?:md|txt|json|jsonl|csv|py|html|xlsx|pdf)))"
)

ACCEPTANCE_GUIDANCE = """[Acceptance Contract]
This is durable multi-step work. A work ledger has been opened automatically.
Update it from actual inventory/tool results, not estimates. A prose claim such
as "done" or "all pass" cannot finish the run. Inspect the produced state,
record verification evidence, and call complete_task only after every ledger
item or required phase is complete and its machine checks pass."""

TurnFn = Callable[..., dict[str, Any]]
ProgressFn = Callable[[dict[str, Any]], None]


def looks_like_batch(text: str) -> bool:
    """True when the prompt itself is a multi-item / do-not-stop job."""
    body = (text or "").strip()
    if body.startswith(HARNESS_PREFIX):
        return True
    return bool(_BATCH_HINT.search(body))


def _goal_active() -> bool:
    try:
        from jaeger_ai.main import get_goal
        goal = get_goal()
        return goal is not None and not bool(getattr(goal, "achieved", False))
    except Exception:  # noqa: BLE001
        return False


def ledger_open() -> bool:
    ledger = active_ledger()
    return ledger is not None and not ledger.completed


def should_run_autonomous(text: str = "") -> bool:
    """Whether THIS prompt should keep the outer loop in control.

    Ledger already open, an active ``/goal``, or batch phrasing. Plain
    ``/auto`` mode without those is *not* enough — that path still uses
    stall-detection continuation, because requiring ``complete_task``
    on "what's 2+2" would burn the step budget.
    """
    if os.environ.get("JAEGER_AUTONOMOUS", "1").strip() == "0":
        return False
    if ledger_open():
        return True
    if _goal_active():
        return True
    return looks_like_batch(text)


def _batch_total(text: str) -> int | None:
    match = _COUNTED_SCOPE.search(text or "")
    if match is None:
        return None
    return max(1, int(match.group(1)))


def _required_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in _PATH_TOKEN.finditer(text or ""):
        raw = (match.group(1) or match.group(2) or "").strip()
        if (
            not raw or "://" in raw or raw in paths
            or not re.search(r"[/\\]|\.(?:md|txt|json|jsonl|csv|py|html|xlsx|pdf)$", raw, re.I)
            or "\n" in raw
        ):
            continue
        paths.append(raw)
    return paths[:24]


def ensure_autonomous_ledger(text: str) -> Any:
    """Open a fail-closed ledger for a high-confidence durable request.

    Counted requests use the stated inventory total. Uncounted but clearly
    durable requests use three observable phases so the run cannot terminate
    before inspection, execution, and verification have each been recorded.
    Existing ledgers are never replaced.
    """
    existing = active_ledger()
    if existing is not None:
        return existing
    if not should_run_autonomous(text):
        return None
    from jaeger_ai.core.runtime.work_ledger import work_ledger

    total = _batch_total(text)
    paths = _required_paths(text)
    verify = {"kind": "paths_exist", "paths": paths} if paths else None
    task_name = " ".join((text or "").strip().split())[:160] or "autonomous task"
    if total is not None:
        result = work_ledger(
            action="create", task_name=task_name,
            total_items=total, remaining_count=total, verify=verify,
        )
    else:
        phases = ["inspect", "execute", "verify"]
        result = work_ledger(
            action="create", task_name=task_name,
            total_items=len(phases), remaining_ids=phases,
            remaining_count=len(phases), verify=verify,
        )
    return active_ledger() if result.get("ok") else None


def _tool_named(tool_activity: list[Any] | None, name: str) -> bool:
    needle = f"▸ {name}("
    for line in tool_activity or []:
        if needle in str(line):
            return True
    return False


def harness_prompt(ledger: Any = None, *, objective: str = "") -> str:
    """Continuation the runner injects between batches."""
    src = ledger if ledger is not None else active_ledger()
    if src is not None:
        done, total = src.done_count(), src.total()
        progress = f"{done}/{total} items processed"
    else:
        run = execution.run_progress()
        progress = f"step {run['step']}/{run['budget']}"
    body = (
        f"{HARNESS_PREFIX}: Batch complete. Progress: {progress}. "
        f"Continuing with next batch. Do not stop until all items are "
        f"finished. Update work_ledger as you go. Call complete_task "
        f"with evidence only when every item is done."
    )
    obj = (objective or execution.run_progress().get("objective") or "").strip()
    if obj:
        return f"{body}\n\nThe objective still in force:\n{obj}"
    return body


def _end(reason: str) -> None:
    if execution.run_active():
        execution.end_run(reason)


def _worker_next(
    answer: str,
    *,
    batch: bool,
    steps_left: int,
    objective: str,
    halt_reason: str | None = None,
) -> str | None:
    """Continuation rule for an isolated worker. Does not touch the
    process-global execution mode — a worker must not flip the main
    session into ``/auto``."""
    if execution.stop_requested():
        return None
    if last_completion():
        return None
    if steps_left <= 0:
        return None
    if continuation.is_loop_breaker(halt_reason):
        return None
    verdict = continuation.classify(answer)
    if verdict in {"question", "blocked"}:
        return None
    if ledger_open() or batch or continuation.hit_inner_cap(halt_reason):
        return harness_prompt(objective=objective)
    if verdict == "continue":
        return harness_prompt(objective=objective)
    return None


def next_continuation_prompt(
    answer: str,
    *,
    tool_activity: list[Any] | None = None,
    force_ledger: bool | None = None,
    isolated: bool = False,
    batch: bool = False,
    steps_left: int | None = None,
    objective: str = "",
    halt_reason: str | None = None,
) -> str | None:
    """The next synthetic prompt, or ``None`` to hand back to the user.

    Two regimes, kept distinct on purpose:

    * A live work ledger (or ``force_ledger``) — continue until
      ``complete_task`` succeeds, a human approval / blocker gate, or
      the budget is spent. A settled-looking prose answer is *not* an
      exit.
    * Continuous execution with no ledger — the existing stall
      detector in :mod:`continuation`. This is what ``/auto`` uses.

    Isolated workers (``delegate_task`` children) pass ``isolated=True``
    so they do not mutate the main session's execution mode.
    """
    if isolated:
        remaining = execution.max_steps() if steps_left is None else steps_left
        return _worker_next(
            answer, batch=batch or ledger_open(),
            steps_left=remaining, objective=objective,
            halt_reason=halt_reason,
        )

    if execution.stop_requested():
        _end("stopped by you")
        execution.clear_stop()
        return None

    if last_completion():
        _end("complete_task")
        return None
    if _tool_named(tool_activity, "complete_task") and not ledger_open():
        _end("complete_task")
        return None

    if continuation.is_loop_breaker(halt_reason):
        _end("loop_breaker")
        return None

    use_ledger = ledger_open() if force_ledger is None else force_ledger
    verdict = continuation.classify(answer)
    inner_cap = continuation.hit_inner_cap(halt_reason)

    if inner_cap:
        if verdict in {"question", "blocked"}:
            _end(verdict)
            return None
        if not execution.run_active():
            execution.begin_run(objective)
        if execution.steps_left() <= 0:
            execution.end_run("budget exhausted")
            return None
        execution.record_step("executing")
        return continuation.continuation_prompt(
            execution.run_progress()["objective"])

    if use_ledger or should_run_autonomous(answer):
        if verdict in {"question", "blocked"}:
            _end(verdict)
            return None
        if not ledger_open() and verdict == "complete" and not _goal_active():
            pass
        elif ledger_open() or _goal_active() or looks_like_batch(answer):
            if not execution.run_active():
                execution.begin_run(objective)
            if execution.steps_left() <= 0:
                execution.end_run("budget exhausted")
                return None
            if verdict == "complete" and execution.needs_verification():
                execution.mark_verified()
                execution.record_step("verifying")
                return continuation.verification_prompt(
                    execution.run_progress()["objective"])
            execution.record_step("executing")
            return harness_prompt(objective=execution.run_progress()["objective"])

    if not execution.is_continuous():
        return None

    if verdict == "complete" and execution.needs_verification():
        if execution.steps_left() <= 0:
            _end("budget spent before verification")
            return None
        execution.mark_verified()
        execution.record_step("verifying")
        return continuation.verification_prompt(execution.run_progress()["objective"])

    if verdict != "continue" or not continuation.enabled():
        _end({
            "question": "question",
            "blocked": "blocked",
            "complete": "complete",
            "empty": "empty",
            "settled": "settled",
        }.get(verdict, verdict))
        return None

    if not execution.run_active():
        execution.begin_run("")
    if execution.steps_left() <= 0:
        execution.end_run("budget exhausted")
        return None
    execution.record_step("executing")
    return continuation.continuation_prompt(execution.run_progress()["objective"])


WORKER_PREAMBLE = (
    "You are a focused worker for the main session. Keep the parent's "
    "chat clean: do the work HERE. For countable items, open a "
    "work_ledger, update it as you go, and call complete_task with "
    "evidence only when every item is done. Do not stop until "
    "complete_task succeeds."
)


class AutonomousGoalRunner:
    """Wrap a single-turn function in a continuous execution loop.

    ``isolated=True`` is the worker path: local step budget, no mutation
    of the main session's execution mode. That is how ``delegate_task``
    keeps the primary conversation unclogged.
    """

    def __init__(
        self,
        *,
        turn_fn: TurnFn | None = None,
        max_steps: int | None = None,
        on_progress: ProgressFn | None = None,
        on_step: ProgressFn | None = None,
        isolated: bool = False,
        batch: bool = False,
    ) -> None:
        self.turn_fn = turn_fn
        self.max_steps = max_steps
        self.on_progress = on_progress
        self.on_step = on_step
        self.isolated = isolated
        self.batch = batch

    def _turn(self) -> TurnFn:
        if self.turn_fn is not None:
            return self.turn_fn
        from jaeger_ai.main import _run_turn
        return _run_turn

    def run(
        self,
        client: Any,
        user_text: str,
        *,
        session_key: str,
        allow_persona: bool = True,
        objective: str = "",
    ) -> dict[str, Any]:
        """Drive turns until ``complete_task``, a human gate, or budget.

        The loop itself lives on :class:`JaegerAgentController` (the
        OpenHands ``_step`` state machine). This method is the
        compatibility surface existing tests and ``run_worker_goal`` call.
        """
        from jaeger_ai.core.runtime.agent_controller import JaegerAgentController

        budget = int(self.max_steps) if self.max_steps else execution.max_steps()
        packed = JaegerAgentController(
            client,
            max_steps=budget,
            turn_fn=self._turn(),
            isolated=self.isolated,
            batch=self.batch,
            on_progress=self.on_progress,
            on_step=self.on_step,
            allow_persona=allow_persona,
        ).run_to_completion(
            user_text, session_key, objective=objective,
        )
        return packed["output"]


def run_autonomous(
    client: Any,
    user_text: str,
    *,
    session_key: str,
    allow_persona: bool = True,
    turn_fn: TurnFn | None = None,
    on_progress: ProgressFn | None = None,
    max_steps: int | None = None,
    isolated: bool = False,
    batch: bool = False,
    objective: str = "",
) -> dict[str, Any]:
    """Convenience wrapper around :class:`AutonomousGoalRunner`."""
    return AutonomousGoalRunner(
        turn_fn=turn_fn, on_progress=on_progress, max_steps=max_steps,
        isolated=isolated, batch=batch,
    ).run(
        client, user_text, session_key=session_key,
        allow_persona=allow_persona, objective=objective,
    )


def run_worker_goal(
    client: Any,
    subtask: str,
    *,
    turn_fn: TurnFn,
    on_progress: ProgressFn | None = None,
    max_steps: int | None = None,
    session_key: str = "delegate",
) -> dict[str, Any]:
    """Isolated autonomous loop for a ``delegate_task`` child.

    The parent session does not see the worker's tool trace — only the
    returned summary (via the completion rail when ``background=True``).
    """
    return run_autonomous(
        client, subtask,
        session_key=session_key,
        allow_persona=False,
        turn_fn=turn_fn,
        on_progress=on_progress,
        max_steps=max_steps,
        isolated=True,
        batch=looks_like_batch(subtask),
        objective=subtask,
    )


__all__ = [
    "HARNESS_PREFIX",
    "ACCEPTANCE_GUIDANCE",
    "WORKER_PREAMBLE",
    "AutonomousGoalRunner",
    "looks_like_batch",
    "should_run_autonomous",
    "ensure_autonomous_ledger",
    "ledger_open",
    "harness_prompt",
    "next_continuation_prompt",
    "run_autonomous",
    "run_worker_goal",
]
