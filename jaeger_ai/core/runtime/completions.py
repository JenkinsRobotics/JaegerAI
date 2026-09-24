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

The resident owner reads a bounded durable outbox and acknowledges only
after a request receipt exists. Stable batch IDs make a lost acknowledgement
replay delivery rather than execute the work again.

Nothing here is brain-specific. A subagent that ran on a cloud lane and
one that ran in-process arrive on the same rail, in the same shape.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import closing
from typing import Any

_MAX_PER_TURN = 5


def _connect():
    # The same durable owner database, not a process-local queue.
    from jaeger_ai.core.gateway.session_store import default_store_path
    conn = sqlite3.connect(default_store_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS completion_outbox (
        id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL,
        acknowledged_at REAL)""")
    conn.commit()
    return conn


def _record(event: dict[str, Any]) -> None:
    event = dict(event)
    ident = str(event.get('id') or uuid.uuid4().hex)
    event['id'] = ident
    with closing(_connect()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO completion_outbox VALUES (?, ?, ?, NULL)",
                     (ident, json.dumps(event), event.get('finished_at') or time.time()))


def record_delegation(*, task: str, result: dict[str, Any],
                      delegation_id: str = '', dispatched_at: float = 0.0,
                      session_id: str = '') -> None:
    """Persist a child result before reporting it to any client."""
    _record({'kind': 'delegation', 'id': delegation_id or uuid.uuid4().hex,
             'task': str(task or ''), 'result': result, 'session_id': session_id,
             'dispatched_at': dispatched_at or time.time(), 'finished_at': time.time()})


def pending_count() -> int:
    with closing(_connect()) as conn:
        return conn.execute('SELECT COUNT(*) FROM completion_outbox WHERE acknowledged_at IS NULL').fetchone()[0]


def pending_batch(layout: Any = None) -> list[dict[str, Any]]:
    """Read a bounded batch. Failed admission must leave it available for retry."""
    for event in _drain_processes(layout):
        _record(event)
    with closing(_connect()) as conn:
        rows = conn.execute('SELECT payload FROM completion_outbox WHERE acknowledged_at IS NULL '
                            'ORDER BY created_at, rowid LIMIT ?', (_MAX_PER_TURN,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def batch_id(events: list[dict[str, Any]]) -> str:
    return 'completion:' + hashlib.sha256(json.dumps([e['id'] for e in events]).encode()).hexdigest()[:32]


def acknowledge(events: list[dict[str, Any]]) -> None:
    with closing(_connect()) as conn, conn:
        conn.executemany('UPDATE completion_outbox SET acknowledged_at=? WHERE id=?',
                         [(time.time(), e['id']) for e in events])


def _drain_processes(layout: Any) -> list[dict[str, Any]]:
    """Finished background processes, from the engine's own queue.

    Best-effort: the completion rail is an enhancement to a turn, and a
    process manager that cannot answer must never stop one.
    """
    if layout is None:
        return []
    try:
        from jaeger_agent.background import processes

        def persist(event):
            _record({
                'kind': 'process', 'id': str(event.get('process_id') or ''),
                'name': str(event.get('name') or ''), 'status': event.get('status'),
                'exit_code': event.get('exit_code'), 'finished_at': event.get('finished_at'),
                'raw': event,
            })
        events = processes.consume_pending_completions(layout, persist=persist) or []
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
    """Take one bounded batch for synchronous legacy consumers.

    The resident owner uses pending_batch/acknowledge around durable admission.
    """
    events = pending_batch(layout)
    acknowledge(events)
    return events


def reset() -> None:
    """Explicit test cleanup; instance switching must not erase durable results."""
    with closing(_connect()) as conn, conn:
        conn.execute('DELETE FROM completion_outbox')


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
    shown = events
    lines = [_describe_delegation(e) if e.get("kind") == "delegation"
             else _describe_process(e) for e in shown]
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
    "completion_prompt", "pending_batch", "acknowledge", "batch_id",
    "consume_pending",
    "next_completion_turn",
    "pending_count",
    "record_delegation",
    "reset",
]
