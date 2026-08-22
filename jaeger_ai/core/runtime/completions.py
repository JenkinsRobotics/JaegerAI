"""Work that finished while the agent was doing something else.

Two things can finish off-turn: a background process started with
``start_background``, and — new here — a subagent dispatched with
``delegate_task(background=True)``. Both need the same thing at the
end: to reach the agent WITHOUT being spliced into a turn already in
flight.

That constraint is the whole design. A completion cannot be appended
between an assistant message and its tool results — that breaks role
alternation, which cloud providers reject outright, and it invalidates
the prompt prefix every local lane depends on for a warm KV cache. So a
completion never interrupts. It waits, and the turn worker turns it
into a NEW user turn once the current one is finished. Hermes reached
the same conclusion by the same route, and calls the rail a completion
queue; this is that rail, over the notification queue JaegerAI's
process manager already had but nobody drained.

Delivery is at-most-once by construction. ``consume_pending`` empties
what it returns, so a completion that has been shown is gone — a queue
that redelivered would have the agent re-reacting to the same finished
job every turn for the rest of the session.

Nothing here is brain-specific. A subagent that ran on a cloud lane and
one that ran in-process arrive on the same rail, in the same shape.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Async delegations that have finished and not yet been surfaced.
# Process completions live in the engine's own queue and are merged in
# by :func:`consume_pending`; this holds only the in-process kind.
_pending: list[dict[str, Any]] = []
_lock = threading.Lock()

# How many completions one synthetic turn may carry. Past this the
# notice stops being something a model can act on and starts being a
# wall of text — the rest wait for the turn after.
_MAX_PER_TURN = 5


def record_delegation(
    *,
    task: str,
    result: dict[str, Any],
    delegation_id: str = "",
    dispatched_at: float = 0.0,
) -> None:
    """Queue a finished background delegation for the next idle moment.

    The payload is deliberately SELF-CONTAINED — the original task text
    travels with the answer. By the time this surfaces, the parent may
    be several turns into something unrelated and have no memory of why
    a subagent existed; a bare result would be unattributable. With the
    task attached the agent can use the answer, or notice the world has
    moved on and drop it.
    """
    with _lock:
        _pending.append({
            "kind": "delegation",
            "id": delegation_id,
            "task": str(task or ""),
            "result": result,
            "dispatched_at": dispatched_at or time.time(),
            "finished_at": time.time(),
        })


def pending_count() -> int:
    """How many delegation completions are waiting. Does not consume."""
    with _lock:
        return len(_pending)


def _drain_delegations() -> list[dict[str, Any]]:
    with _lock:
        drained = list(_pending)
        _pending.clear()
    return drained


def _drain_processes(layout: Any) -> list[dict[str, Any]]:
    """Finished background processes, from the engine's own queue.

    Best-effort: the completion rail is an enhancement to a turn, and a
    process manager that cannot answer must never stop one.
    """
    if layout is None:
        return []
    try:
        from jaeger_agent.background import processes

        events = processes.consume_pending_completions(layout) or []
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        out.append({
            "kind": "process",
            "id": str(event.get("id") or event.get("process_id") or ""),
            "name": str(event.get("name") or ""),
            "status": str(event.get("status") or "finished"),
            "exit_code": event.get("exit_code"),
            "finished_at": event.get("finished_at") or time.time(),
            "raw": event,
        })
    return out


def consume_pending(layout: Any = None) -> list[dict[str, Any]]:
    """Every completion waiting, oldest first. Empties the queues."""
    events = _drain_delegations() + _drain_processes(layout)
    events.sort(key=lambda e: float(e.get("finished_at") or 0.0))
    return events


def reset() -> None:
    """Drop everything queued — for tests and instance switches."""
    with _lock:
        _pending.clear()


# ── turning completions into a turn ─────────────────────────────────


def _one_line(text: str, limit: int = 400) -> str:
    return " ".join(str(text or "").split())[:limit]


def _describe_delegation(event: dict[str, Any]) -> str:
    result = event.get("result") or {}
    task = _one_line(event.get("task"), 200)
    if not isinstance(result, dict):
        return f"- Subagent task {task!r} finished: {_one_line(result)}"
    if result.get("delegated") is False or result.get("ok") is False:
        why = _one_line(result.get("error") or "no reason given", 200)
        return f"- Subagent task {task!r} FAILED: {why}"
    answer = _one_line(
        result.get("summary") or result.get("answer") or result.get("result") or "",
        800,
    )
    return f"- Subagent task {task!r} finished. Its answer: {answer}"


def _describe_process(event: dict[str, Any]) -> str:
    name = event.get("name") or event.get("id") or "background process"
    status = event.get("status") or "finished"
    code = event.get("exit_code")
    tail = f" (exit {code})" if code is not None else ""
    return (
        f"- Background process {name!r} {status}{tail}. "
        f"Use check_background to read its output."
    )


def completion_prompt(events: list[dict[str, Any]]) -> str:
    """The synthetic user turn that delivers ``events``.

    Framed as a report of something that happened, with an explicit
    instruction about judgement: work dispatched several turns ago may
    have been overtaken, and an agent that mechanically acts on every
    stale result is worse than one that reads it and moves on.
    """
    shown = events[:_MAX_PER_TURN]
    lines = [_describe_delegation(e) if e.get("kind") == "delegation"
             else _describe_process(e) for e in shown]
    overflow = len(events) - len(shown)
    if overflow > 0:
        lines.append(f"- …and {overflow} more, which will follow.")
    return (
        "SYSTEM NOTICE — background work finished while you were busy:\n"
        + "\n".join(lines)
        + "\n\nUse these results if they still serve what the user is "
        "doing now. If the work has been overtaken, say so briefly and "
        "carry on — do not restart it, and do not report this notice "
        "back verbatim."
    )


def next_completion_turn(layout: Any = None) -> str | None:
    """The prompt for a completion turn, or ``None`` when nothing waits.

    Called by the turn worker at the one safe moment: after a turn has
    finished and before the prompt goes back to the user.
    """
    events = consume_pending(layout)
    if not events:
        return None
    return completion_prompt(events)


__all__ = [
    "completion_prompt",
    "consume_pending",
    "next_completion_turn",
    "pending_count",
    "record_delegation",
    "reset",
]
