"""Standalone multi-agent orchestration implementing OrchestrationPort.

Synthesizes:
- openai-codex (`control/spawn.rs`, `control/mailbox.rs`):
  strict permission-profile intersection on spawn (children NEVER exceed parent
  sandbox authority) + durable eviction-safe agent mailboxes.
- opencode (`subagent-job.ts`, `subagent-depth.ts`) & hermes-agent (`subagent_lifecycle.py`, `cron/scheduler.py`):
  depth-capped background subagents with push-based completion delivery onto EventBusPort
  and tick-based cron scheduling.
- ag2 (`network/hub/arbiter.py`): inline HubArbiter policy gate before mailbox write.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from jaeger_contracts import EventBusPort, ExecutionLoopPort, SandboxProfile


def intersect_sandbox_profiles(parent: SandboxProfile, requested: SandboxProfile | None) -> SandboxProfile:
    """Intersect child sandbox with parent so a child can NEVER widen authority (codex invariant)."""
    if requested is None:
        return parent

    p_ws = parent.workspace.expanduser().resolve(strict=False)
    c_ws = requested.workspace.expanduser().resolve(strict=False)
    # Child workspace must stay inside parent workspace (else clamp to parent workspace)
    effective_ws = c_ws if (c_ws == p_ws or p_ws in c_ws.parents) else p_ws

    p_writable = {p.expanduser().resolve(strict=False) for p in (parent.workspace, *parent.writable_roots)}
    c_writable = [
        r for r in (p.expanduser().resolve(strict=False) for p in requested.writable_roots)
        if any(r == pw or pw in r.parents for pw in p_writable)
    ]

    return SandboxProfile(
        workspace=effective_ws,
        writable_roots=tuple(dict.fromkeys(c_writable)),
        read_only_subpaths=tuple(dict.fromkeys((*parent.read_only_subpaths, *requested.read_only_subpaths))),
        denied_read_paths=tuple(dict.fromkeys((*parent.denied_read_paths, *requested.denied_read_paths))),
        denied_write_paths=tuple(dict.fromkeys((*parent.denied_write_paths, *requested.denied_write_paths))),
        allow_network=bool(parent.allow_network and requested.allow_network),
        allow_tmp_writes=bool(parent.allow_tmp_writes and requested.allow_tmp_writes),
        read_only_default=bool(parent.read_only_default or requested.read_only_default),
    )


ArbiterFn = Callable[[str, str, Mapping[str, Any]], bool]


class DurableMailbox:
    """SQLite eviction-safe inter-agent mailbox with inline HubArbiter gate (codex + ag2)."""

    def __init__(self, state_dir: Path, *, arbiter: ArbiterFn | None = None) -> None:
        self._dir = state_dir.expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "mailboxes.sqlite3"
        self._arbiter = arbiter
        with sqlite3.connect(str(self._db)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS mail (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )"""
            )

    def send(self, sender: str, recipient: str, payload: Mapping[str, Any]) -> int:
        if self._arbiter is not None and not self._arbiter(sender, recipient, payload):
            raise PermissionError(f"HubArbiter denied mail from {sender!r} to {recipient!r}")
        with sqlite3.connect(str(self._db)) as conn:
            cur = conn.execute(
                "INSERT INTO mail(sender, recipient, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (sender, recipient, json.dumps(dict(payload), default=str), time.time()),
            )
            return int(cur.lastrowid or 0)

    def drain(self, recipient: str) -> list[dict[str, Any]]:
        with sqlite3.connect(str(self._db)) as conn:
            rows = conn.execute(
                "SELECT id, sender, payload_json, created_at FROM mail WHERE recipient = ? AND delivered = 0 ORDER BY id ASC",
                (recipient,),
            ).fetchall()
            if rows:
                ids = [(r[0],) for r in rows]
                conn.executemany("UPDATE mail SET delivered = 1 WHERE id = ?", ids)
        return [
            {"id": r[0], "sender": r[1], "payload": json.loads(r[2]), "created_at": r[3]}
            for r in rows
        ]


LoopFactory = Callable[[str, str, SandboxProfile | None], ExecutionLoopPort]


class SubagentOrchestrator:
    """Depth-capped background subagent runner with push completion delivery (OrchestrationPort)."""

    def __init__(
        self,
        *,
        loop_factory: LoopFactory,
        events: EventBusPort | None = None,
        mailbox: DurableMailbox | None = None,
        max_depth: int = 3,
        max_workers: int = 4,
        name: str = "jaeger_orchestration",
    ) -> None:
        self._name = name
        self._loop_factory = loop_factory
        self._events = events
        self._mailbox = mailbox
        self._max_depth = max(1, int(max_depth))
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._lock = threading.Lock()
        self._futures: dict[str, Future[Mapping[str, Any]]] = {}
        self._profiles: dict[str, SandboxProfile | None] = {}

    @property
    def name(self) -> str:
        return self._name

    def effective_profile(self, agent_id: str) -> SandboxProfile | None:
        return self._profiles.get(agent_id)

    def spawn(
        self,
        task: str,
        *,
        role: str,
        parent_profile: SandboxProfile | None = None,
        requested_profile: SandboxProfile | None = None,
        depth: int = 1,
        parent_id: str = "coordinator",
    ) -> str:
        if depth > self._max_depth:
            raise RecursionError(f"Subagent depth {depth} exceeds max_depth={self._max_depth}")

        child_id = f"sub_{role}_{uuid.uuid4().hex[:8]}"
        effective = (
            intersect_sandbox_profiles(parent_profile, requested_profile)
            if parent_profile is not None
            else requested_profile
        )
        self._profiles[child_id] = effective

        def _run() -> Mapping[str, Any]:
            loop = self._loop_factory(child_id, role, effective)
            result = dict(loop.run_turn(task))
            result["agent_id"] = child_id
            result["role"] = role
            if self._mailbox is not None:
                self._mailbox.send(child_id, parent_id, {"kind": "background_result", "result": result})
            if self._events is not None:
                self._events.publish(
                    "subagent.completed",
                    {"agent_id": child_id, "role": role, "verdict": result.get("verdict")},
                    session_id=parent_id,
                )
            return result

        with self._lock:
            self._futures[child_id] = self._pool.submit(_run)
        return child_id

    def await_result(self, agent_id: str, *, timeout: float = 30.0) -> Mapping[str, Any]:
        with self._lock:
            fut = self._futures.get(agent_id)
        if fut is None:
            raise KeyError(f"Unknown subagent id: {agent_id!r}")
        return fut.result(timeout=timeout)

    def close(self) -> None:
        self._pool.shutdown(wait=True)


@dataclass
class CronJob:
    job_id: str
    interval_s: float
    fn: Callable[[], Any]
    last_run: float = 0.0
    runs: int = 0
    errors: int = 0


class CronScheduler:
    """Deterministic tick-driven recurring job scheduler (hermes-agent pattern)."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._jobs: dict[str, CronJob] = {}

    def register(self, job_id: str, interval_s: float, fn: Callable[[], Any]) -> None:
        self._jobs[job_id] = CronJob(job_id=job_id, interval_s=max(0.01, interval_s), fn=fn)

    def tick(self) -> list[str]:
        now = self._clock()
        fired: list[str] = []
        for job in self._jobs.values():
            if job.last_run == 0.0 or (now - job.last_run) >= job.interval_s:
                job.last_run = now
                try:
                    job.fn()
                    job.runs += 1
                    fired.append(job.job_id)
                except Exception:
                    job.errors += 1
        return fired
