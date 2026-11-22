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
not replace it. The canonical execution owner calls
:func:`run_continued_turn` around a single inner ReAct step. Surfaces
that still loop locally (the TUI worker) call
:func:`next_continuation_prompt`; ``run_command`` calls
:class:`AutonomousGoalRunner`.
"""

from __future__ import annotations

from pathlib import Path

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
_COUNTED_SCOPE = re.compile(
    r"(?i)\b(\d{1,7})\s+(?:items?|files?|rows?|entries|notes?|folders?|records|bookmarks?)\b"
)
_FILE_EXTENSIONS = r"md|txt|json|jsonl|csv|py|html|xlsx|pdf|docx|pptx|ics|png|jpe?g|webp|mp4|mov|wav|mp3|js|ts"
_PATH_TOKEN = re.compile(
    rf"(?<!https:)(?<!http:)(?:`([^`]+)`|(?<![\w./~-])([\w./~-]+\.(?:{_FILE_EXTENSIONS}))\b)", re.I
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
    return body.startswith("/goal")


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


def conversation_only(text: str) -> bool:
    """Explicit single-response requests must not inherit unrelated job state.

    This is deliberately narrow. General tasks still use the existing work
    lifecycle; an explicit batch or /goal is never classified as small talk.
    """
    value = (text or "").strip()
    if looks_like_batch(value):
        return False
    return bool(
        re.fullmatch(r"(?i)(?:hi|hello|hey|ping|thanks|thank you)[!. ]*", value)
        or re.match(r"(?i)^(?:please\s+)?reply\s+(?:with\s+)?exactly\b", value)
        or re.search(r"(?i)\b(?:do not|don't) use (?:any )?tools\b", value)
    )


def should_run_autonomous(text: str = "") -> bool:
    """Whether THIS prompt should keep the outer loop in control.

    Ledger already open, an active ``/goal``, or batch phrasing. Plain
    ``/auto`` mode without those is *not* enough — that path still uses
    stall-detection continuation, because requiring ``complete_task``
    on "what's 2+2" would burn the step budget.
    """
    if os.environ.get("JAEGER_AUTONOMOUS", "1").strip() == "0":
        return False
    if conversation_only(text):
        return False
    if ledger_open():
        return True
    if _goal_active():
        return True
    # Durable execution is an explicit host/user state transition.  Natural
    # language is never an authority signal: it cannot promote an ordinary
    # chat turn into a long-running worker loop.  `/goal` remains the explicit
    # textual admission command; existing ledgers/goals remain resumable.
    return (text or "").lstrip().startswith("/goal")


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
            or not re.search(rf"[/\\]|\.(?:{_FILE_EXTENSIONS})$", raw, re.I)
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
    if conversation_only(text):
        return None
    existing = active_ledger()
    if existing is not None:
        return existing
    if continuation.is_continuation_prompt(text):
        return None
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
    obj = (objective or execution.run_progress().get("objective")
           or (src.task_name if src is not None else "")).strip()
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
    # An open ledger means the accepted objective is not finished. A
    # trailing "Want me to start?" is a mid-work checkpoint the model
    # added for tone, not a new permission gate on accepted work.
    if verdict in {"question", "blocked"} and not ledger_open():
        return None
    if verdict == "blocked":
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
    if conversation_only(objective):
        return None
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
    inner_cap = continuation.hit_inner_cap(halt_reason)
    verdict = continuation.classify(answer, at_inner_cap=inner_cap)

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


def missing_named_paths(text: str) -> list[str]:
    """Paths named in ``text`` that do not exist where the tools would look.

    Relative paths resolve the way the file and shell tools resolve them:
    the bound project, the instance root (``workspace/...``) and the
    effective workspace. Used only to decide whether a follow-up is
    warranted, never to fail a turn.
    """
    names = _required_paths(text)
    if not names:
        return []
    bases: list[Path] = []
    try:
        from jaeger_agent.core import workspace as _ws
        project = _ws.get_project_root()
        if project is not None:
            bases.append(Path(project))
        else:
            layout = _ws._require_layout()
            bases.extend([Path(layout.root), Path(_ws.get_effective_workspace_dir())])
    except Exception:  # noqa: BLE001 — no instance bound: only absolute paths count
        pass
    missing = []
    for name in names:
        candidate = Path(name).expanduser()
        if candidate.is_absolute():
            found = candidate.exists()
        else:
            found = any((base / candidate).exists() for base in bases)
        if not found:
            missing.append(name)
    return missing


MISSING_PATHS_NOTE = (
    "Check before you finish: these paths named in the request do not exist "
    "yet: {paths}. If the request asked you to produce them, finish that and "
    "confirm they exist with a tool. If they were supposed to exist already, "
    "say so plainly instead of creating them."
)


#: Tools that only observe. Anything else (shell, writes, edits, git, sql, ...)
#: may have changed state, so its result gets an independent check.
READ_ONLY_TOOLS = frozenset({
    "read_file", "search_files", "list_skill_dir", "list_tools", "describe_tool", "load_tools",
    "search_memory", "recall", "recall_insight", "web_search", "web_extract", "update_plan",
    "list_skills", "get_time", "calculate", "clarify", "todo", "board_view", "see_screen",
    "ocr_window", "vision_analyze", "list_mailboxes", "list_mail", "read_mail",
})

CHECK_STEP = (
    "[Check step] Before this result is reported, verify it independently. For each fact "
    "your answer states (an id or SHA, a count, a file and its contents, a test result, a "
    "setting), re-derive what it SHOULD be from the original source of truth by a different "
    "route than the one you used, then confirm what it IS now with a read-only tool. Examples: "
    "for a restored git ref, read the reflog to see which commit it pointed at before, then "
    "rev-parse the ref; for a file, read it back; for code, run the tests; for a database, "
    "query it. If any check disagrees, fix the work and check again. Then reply with the "
    "final result and the evidence you checked. If something cannot be verified, say so "
    "plainly. The objective:\n{objective}"
)


#: A check that itself changed state (it fixed something) earns one re-check.
MAX_CHECKS = 2


def changed_state(tools_used: list[str] | tuple[str, ...]) -> bool:
    return any(t and t not in READ_ONLY_TOOLS for t in tools_used)


def artifact_errors(objective: str, *, since: float) -> list[str]:
    """Check newly written, named Office outputs in the admitted workspace."""
    from jaeger_ai.core.entity.verification import artifact_format_error
    from jaeger_agent.core.workspace import get_effective_workspace_dir, get_project_root
    try:
        root = Path(get_project_root() or get_effective_workspace_dir()).resolve()
    except (RuntimeError, TypeError):
        return []
    errors = []
    for name in _required_paths(objective):
        path = (root / Path(name).expanduser()).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_mtime < since:
            continue
        if error := artifact_format_error(path):
            errors.append(error)
    return errors


def interactive_followup(answer: str, objective: str, halt_reason: str | None,
                         *, paths_checked: bool, tools_used: list[str] | tuple[str, ...] = (),
                         checked: bool = True, checks_done: int | None = None,
                         last_tools: list[str] | tuple[str, ...] | None = None) -> str | None:
    """Next prompt for an operator's turn-owned request, or ``None`` to reply.

    A durable background task keeps the strict ledger contract (``harness_prompt``
    until ``complete_task``). An interactive request whose answer IS the
    deliverable (a hash, a count, a summary) cannot produce a file receipt, so
    re-prompting it "do not stop until all items are finished" only burned
    model calls (2026-10-09 probe: five extra calls after a correct answer).
    Continue only on evidence of unfinished work: the inner budget tripped,
    the model said it is not done, or files named in the request are missing
    (one neutral check; never an instruction to invent them).

    Stop after verified: once a check step ran and that check only observed
    (read-only tools), the result is verified and is replied, whatever the
    wording of the answer. Re-sending the objective after a passed check made
    the model redo finished work until the cap (SOTA CLAR-03 2026-10-09:
    three extra rounds after a correct, read-back file).
    """
    done = int(checked) if checks_done is None else int(checks_done)
    check_changed = changed_state(last_tools or ())
    if checks_done and not check_changed and not continuation.hit_inner_cap(halt_reason):
        return None
    if continuation.hit_inner_cap(halt_reason):
        return continuation.continuation_prompt(objective)
    verdict = continuation.classify(answer)
    if verdict in {"question", "blocked"}:
        return None
    if verdict in {"continue", "empty"}:
        return continuation.continuation_prompt(objective)
    if not paths_checked:
        # Only paths the request asks to produce: a file it merely names
        # (summarise scripts/x.py) sits outside the workspace and is not
        # missing work (R13 spent a pass proving an existing script exists).
        missing = missing_deliverable_paths(objective)
        if missing:
            return MISSING_PATHS_NOTE.format(paths=", ".join(missing[:8]))
    if changed_state(tools_used) and (done == 0 or (check_changed and done < MAX_CHECKS)):
        # Verify before complete: an independent re-derivation of every claimed
        # fact after any turn that may have changed state, and once more if the
        # check had to fix something. Slower, not luckier.
        return CHECK_STEP.format(objective=objective)
    return None


def run_continued_turn(
    turn_fn: TurnFn,
    prompt: str,
    *,
    objective: str = "",
    is_cancelled: Callable[[], bool] | None = None,
    max_steps: int | None = None,
    on_checkpoint: ProgressFn | None = None,
    durable: bool = False,
    interactive: bool = False,
) -> dict[str, Any]:
    """Re-fire one inner turn until the stall/ledger rule says stop.

    This is the owner-side loop the local bridge used to run around
    ``run_for_voice``. One admitted request, several inner steps, one
    final answer with separate intermediate checkpoints. Continuation prompts are not new user messages
    and must not be persisted as such. Cancellation, a loop-breaker
    halt, a turn error, or the step budget ends the run.
    """
    from jaeger_ai.core.runtime.work_ledger import pause_active_ledger

    current = prompt
    goal = objective or prompt
    budget = execution.max_steps() if max_steps is None else max(1, int(max_steps))
    step = 0
    checkpoints: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    nxt = None
    paths_checked = False
    checks = 0
    tools_used: list[str] = []
    last_answer = ""
    import time
    run_started = time.time()
    format_corrections = 0

    with execution.run_scope(goal, budget=budget):
        while True:
            if durable and last_completion():
                # A completed durable slice survives an owner restart. Return its
                # actual receipt to the owner for revalidation; do not ask the model
                # to perform completed effects again.
                result = {"text": last_completion().get("summary", ""), "halt_reason": None}
                break
            if is_cancelled is not None and is_cancelled():
                result = {
                    "text": "",
                    "error": "Cancelled before execution",
                    "halt_reason": "interrupted",
                }
                break
            result = dict(turn_fn(current) or {})
            ans = str(result.get("text") or "").strip()
            if result.get("error") or execution.stop_requested():
                break
            if is_cancelled is not None and is_cancelled():
                result = {**result, "halt_reason": "interrupted"}
                break
            nxt = None
            why = ""
            halt = result.get("halt_reason")
            if continuation.is_loop_breaker(halt):
                break
            step_tools = [str(t) for t in (result.get("tools_used") or [])]
            tools_used.extend(step_tools)
            if ans:
                last_answer = ans
            invalid = artifact_errors(goal, since=run_started)
            if invalid:
                if format_corrections >= 1 or step >= budget or last_completion():
                    result = {**result, "status": "failed", "error": "; ".join(invalid),
                              "halt_reason": "invalid_artifact"}
                    break
                format_corrections += 1
                nxt = ("Independent artifact validation failed: " + "; ".join(invalid) +
                       ". Repair these outputs and verify they can be read before claiming completion. "
                       "The objective remains:\n" + goal)
                why = "artifact format correction"
            elif durable and not last_completion() and interactive and not ledger_open():
                nxt = interactive_followup(ans, goal, halt, paths_checked=paths_checked,
                                           tools_used=tools_used, checks_done=checks,
                                           last_tools=step_tools if checks else None)
                why = "owner verification follow-up"
                if nxt and nxt.startswith(MISSING_PATHS_NOTE[:30]):
                    paths_checked = True
                elif nxt and nxt.startswith(CHECK_STEP[:12]):
                    checks += 1
                elif nxt is None and not ans and last_answer:
                    # Verified and done, but the last inner turn said nothing:
                    # reply with the latest real answer, never an empty one.
                    result = {**result, "text": last_answer}
            elif durable and not last_completion():
                nxt = harness_prompt(objective=goal)
                why = "durable task not completed yet"
            elif ledger_open() or continuation.hit_inner_cap(halt):
                why = "work ledger still open" if ledger_open() else f"inner loop hit its cap ({halt})"
                nxt = next_continuation_prompt(
                    ans, force_ledger=ledger_open(), halt_reason=halt, objective=goal,
                )
            elif continuation.enabled():
                if continuation.classify(ans) == "continue":
                    nxt = continuation.continuation_prompt(goal)
                    why = "answer reads as unfinished"
            if nxt and step < budget:
                checkpoint = {"text": ans, "step": step, "halt_reason": halt, "reason": why}
                checkpoints.append(checkpoint)
                if on_checkpoint is not None:
                    on_checkpoint(checkpoint)
                step += 1
                current = nxt
                continue
            break

        unfinished = bool(nxt or continuation.hit_inner_cap(result.get("halt_reason")) or ledger_open())
        if (durable and unfinished and step >= budget and not last_completion()
                and not result.get("error") and not continuation.is_loop_breaker(result.get("halt_reason"))):
            result = {**result, "halt_reason": "yielded"}
        elif unfinished and step >= budget and not last_completion() and not result.get("error"):
            result = {**result, "status": "failed", "halt_reason": "continuation_budget_exhausted",
                      "error": "Continuation budget exhausted before the request completed. Partial work remains available."}
        elif continuation.hit_inner_cap(result.get("halt_reason")) and not result.get("error"):
            # A blocked/question verdict can end continuation before the budget.
            # Preserve that explanation, but an exhausted inner loop is never
            # evidence that the requested work completed.
            result = {**result, "status": "failed",
                      "error": "Execution stopped at its tool/iteration limit before the request completed. Review the partial result and stated blockers."}
        halt = result.get("halt_reason")
        if result.get("error") or (halt != "yielded" and continuation.is_loop_breaker(halt)):
            pause_active_ledger(str(result.get("error") or halt))
        return {**result, "checkpoints": checkpoints, "continuation_steps": step}


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
    "run_continued_turn",
    "run_autonomous",
    "run_worker_goal",
]


def missing_deliverable_paths(text: str) -> list[str]:
    """Missing paths the request asks Jaeger to produce, not ones it only reads.

    "Summarize what scripts/audit-guard.py does" names an input that lives in a
    repo outside the workspace; treating it as a missing deliverable made the
    lead write a receipt file and spend minutes re-verifying (R13 demo, 240s).
    A deliverable is a path after to/into/as/at or right after save/create/
    write/export/generate (optionally "a file called").
    """
    out = []
    for name in missing_named_paths(text):
        pat = (r"(?:\b(?:to|into|as|at|save|saved|create|write|export|generate|produce|deliver)\s+"
               r"(?:(?:a|the|new)\s+)?(?:file\s+)?(?:called\s+|named\s+)?[`'\"]?)" + re.escape(name))
        if re.search(pat, text or "", re.I):
            out.append(name)
    return out
