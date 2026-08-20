"""Who is working a background task, since when, and is it still alive.

Deep Think runs tasks in-process with no claim, no heartbeat, and no
runtime ceiling. A task that wedges — a tool blocked on a socket, a
model call that never returns, a daemon killed with `kill -9` mid-task —
stays marked ``in_progress`` forever. Nothing notices, nothing retries,
and the queue behind it never moves. The failure is invisible by
construction: everything looks like work in progress.

This is Kanban's answer, reduced to the three primitives that actually
do the work:

  * **a claim** — which process, on which host, took this task and when;
  * **a heartbeat** — a timestamp the worker refreshes as it goes, so
    "still working" is something it keeps asserting rather than
    something assumed from the claim;
  * **a ceiling** — ``max_runtime_s``, after which a task is over budget
    whether or not it is alive.

A claim is stale when the worker is gone (PID no longer alive), silent
(heartbeat older than the grace window), or over its ceiling. Stale
claims are released so the task returns to the queue.

**Why a sidecar and not the board card.** The board's ``update`` takes a
fixed field allowlist and lives in the pinned ``jaeger-agent`` package;
adding fields there is a dependency release, not an edit. Claims are
also a different KIND of state from the card: a card is what the work
IS, a claim is who is holding it right now, and the second is worth
losing on a fresh install while the first is not.

**PID liveness only counts on the same host.** If the instance dir is
shared, a PID from another machine says nothing about a local process —
worse, it may match an unrelated local one. A foreign claim is judged by
its heartbeat alone.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import signal
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# A worker refreshes its heartbeat at least this often; a claim that has
# not been touched in this long is treated as silent. Generous, because
# a single Deep Think step (a big model call on a cold local model) can
# legitimately run for minutes without a chance to check in.
HEARTBEAT_GRACE_S = 600.0

# Default ceiling on one task. Past this the task is over budget even if
# its worker is healthy and chatty — an hour of one background task is
# a task that has gone wrong in a way it cannot self-detect.
DEFAULT_MAX_RUNTIME_S = 3600.0

_STORE_NAME = "task_claims.json"


def _store_path(layout: Any) -> Path | None:
    root = getattr(layout, "root", None)
    if root is None:
        return None
    return Path(str(root)) / "memory" / _STORE_NAME


def _load(layout: Any) -> dict[str, dict[str, Any]]:
    path = _store_path(layout)
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a corrupt store must not stop work
        return {}
    return data if isinstance(data, dict) else {}


def _save(layout: Any, claims: dict[str, dict[str, Any]]) -> bool:
    path = _store_path(layout)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(claims, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        return False
    return True


def _pid_alive(pid: int) -> bool:
    """Whether ``pid`` names a live process on THIS host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, owned by someone else — still alive for our purposes.
        return True
    except OSError:
        return False
    return True


# ── claiming ────────────────────────────────────────────────────────


def claim(
    layout: Any,
    task_id: str,
    *,
    max_runtime_s: float = DEFAULT_MAX_RUNTIME_S,
    detail: str = "",
) -> dict[str, Any]:
    """Record that THIS process is working ``task_id``.

    Overwrites any existing claim: the caller reclaims stale work before
    picking it up, so a claim landing on top of another means the old
    one was already judged dead.
    """
    now = time.time()
    record = {
        "task_id": str(task_id),
        "pid": os.getpid(),
        "host": platform.node(),
        "claimed_at": now,
        "heartbeat_at": now,
        "max_runtime_s": float(max_runtime_s),
        "detail": str(detail or ""),
    }
    claims = _load(layout)
    claims[str(task_id)] = record
    _save(layout, claims)
    return record


def heartbeat(layout: Any, task_id: str, *, detail: str = "") -> bool:
    """Assert that work on ``task_id`` is still progressing.

    Returns False when there is no claim to refresh — which means
    something else already reclaimed this task, and the caller should
    stop rather than keep working on a task the queue has handed on.
    """
    claims = _load(layout)
    record = claims.get(str(task_id))
    if not record:
        return False
    record["heartbeat_at"] = time.time()
    if detail:
        record["detail"] = str(detail)
    claims[str(task_id)] = record
    _save(layout, claims)
    return True


def release(layout: Any, task_id: str) -> bool:
    """Drop the claim on ``task_id`` — finished, failed, or handed back."""
    claims = _load(layout)
    if str(task_id) not in claims:
        return False
    claims.pop(str(task_id), None)
    _save(layout, claims)
    return True


def active_claims(layout: Any) -> list[dict[str, Any]]:
    """Every claim on record, whether healthy or not."""
    return list(_load(layout).values())


@contextlib.contextmanager
def beating(
    layout: Any,
    task_id: str,
    *,
    interval_s: float = 60.0,
) -> Iterator[None]:
    """Keep ``task_id``'s heartbeat fresh for the duration of the block.

    A Deep Think step is one long blocking call — a plan, an agent loop,
    a verification pass — with no natural place to check in from. So the
    heartbeat runs on its own daemon thread and the worker just does its
    work. Without this the grace window would have to be longer than the
    slowest imaginable task, which would make it useless for detecting
    the wedge it exists to detect.

    Daemon thread, and best-effort: a store that will not write costs a
    heartbeat, never the task.
    """
    stop = threading.Event()

    def _beat() -> None:
        while not stop.wait(interval_s):
            try:
                if not heartbeat(layout, task_id):
                    return  # reclaimed by someone else — stop asserting
            except Exception:  # noqa: BLE001
                return

    thread = threading.Thread(
        target=_beat, name=f"heartbeat-{task_id}", daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)


# ── judging ─────────────────────────────────────────────────────────


def stale_reason(record: dict[str, Any], *, now: float | None = None) -> str | None:
    """Why this claim is stale, or ``None`` when it is healthy.

    Checked most-certain first: a dead process is a fact, a silent one
    is an inference, and an over-budget one is a policy call. The
    returned string goes into the task's failure evidence, so it has to
    read as a reason rather than a code.
    """
    now = time.time() if now is None else now
    pid = int(record.get("pid") or 0)
    host = str(record.get("host") or "")
    claimed_at = float(record.get("claimed_at") or 0.0)
    beat = float(record.get("heartbeat_at") or claimed_at)
    ceiling = float(record.get("max_runtime_s") or DEFAULT_MAX_RUNTIME_S)

    same_host = host == platform.node()
    if same_host and not _pid_alive(pid):
        return f"worker process {pid} is gone"

    silence = now - beat
    if silence > HEARTBEAT_GRACE_S:
        return (
            f"no heartbeat for {int(silence)}s "
            f"(grace {int(HEARTBEAT_GRACE_S)}s)"
        )

    runtime = now - claimed_at
    if ceiling > 0 and runtime > ceiling:
        return f"over its {int(ceiling)}s runtime ceiling ({int(runtime)}s)"
    return None


def is_stale(record: dict[str, Any], *, now: float | None = None) -> bool:
    return stale_reason(record, now=now) is not None


# ── reclaiming ──────────────────────────────────────────────────────


def terminate_worker(record: dict[str, Any], *, kill_after_s: float = 5.0) -> str:
    """Stop the process holding an over-budget claim.

    ``SIGTERM``, then ``SIGKILL`` if it is still there — the escalation
    Kanban uses, and the reason a ceiling means anything: a task that is
    over budget but healthy will not stop on its own.

    Only ever targets a live PID on this host, and never this process:
    the in-process Deep Think worker IS the daemon, and signalling
    ourselves would take the whole queue down to reclaim one task.
    """
    pid = int(record.get("pid") or 0)
    if str(record.get("host") or "") != platform.node():
        return "not this host — left alone"
    if pid == os.getpid():
        return "in-process worker — claim released, not signalled"
    if not _pid_alive(pid):
        return "already gone"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return f"SIGTERM failed: {exc}"

    deadline = time.time() + max(0.0, kill_after_s)
    while time.time() < deadline:
        if not _pid_alive(pid):
            return "stopped on SIGTERM"
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError as exc:
        return f"SIGKILL failed: {exc}"
    return "killed after SIGTERM timeout"


def reclaim_stale(
    layout: Any,
    *,
    now: float | None = None,
    terminate: bool = True,
) -> list[dict[str, Any]]:
    """Release every stale claim. Returns what was reclaimed and why.

    Call this BEFORE picking up work: a task whose worker died is
    otherwise stuck ``in_progress`` forever, and the queue behind it
    never moves.
    """
    claims = _load(layout)
    if not claims:
        return []

    reclaimed: list[dict[str, Any]] = []
    kept: dict[str, dict[str, Any]] = {}
    for task_id, record in claims.items():
        reason = stale_reason(record, now=now)
        if reason is None:
            kept[task_id] = record
            continue
        action = ""
        if terminate and "runtime ceiling" in reason:
            action = terminate_worker(record)
        reclaimed.append({
            "task_id": task_id,
            "reason": reason,
            "action": action,
            "pid": record.get("pid"),
            "host": record.get("host"),
            "detail": record.get("detail", ""),
        })
    if reclaimed:
        _save(layout, kept)
    return reclaimed


def describe_reclaim(entry: dict[str, Any]) -> str:
    """One operator-readable line for a reclaimed task."""
    action = entry.get("action")
    tail = f"; {action}" if action else ""
    return (
        f"task {entry.get('task_id')} reclaimed — "
        f"{entry.get('reason')}{tail}"
    )


__all__ = [
    "DEFAULT_MAX_RUNTIME_S",
    "HEARTBEAT_GRACE_S",
    "active_claims",
    "beating",
    "claim",
    "describe_reclaim",
    "heartbeat",
    "is_stale",
    "reclaim_stale",
    "release",
    "stale_reason",
    "terminate_worker",
]
