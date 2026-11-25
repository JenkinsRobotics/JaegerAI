"""Durable SQLite-backed workflow DAG engine with pause/resume & approval interrupts.

Pure Python stdlib + SQLite (zero product/runtime imports). Designed for
multi-step user tasks (inbox sweeps, file organization batches, YouTube video
production pipelines) that must survive single-turn budgets and restarts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence


class WorkflowError(RuntimeError):
    """Raised on invalid workflow definitions or missing runs/steps."""


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    OUTCOME_UNKNOWN = "outcome_unknown"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    name: str
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    requires_approval: bool = False
    idempotent: bool = False
    max_retries: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "params": dict(self.params),
            "depends_on": list(self.depends_on),
            "requires_approval": bool(self.requires_approval),
            "idempotent": bool(self.idempotent),
            "max_retries": int(self.max_retries),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStep":
        step_id = str(data.get("id") or "").strip()
        if not step_id:
            raise WorkflowError("workflow step requires a non-empty 'id'")
        name = str(data.get("name") or step_id).strip()
        deps = tuple(str(d).strip() for d in (data.get("depends_on") or []) if str(d).strip())
        return cls(
            id=step_id,
            name=name,
            action=str(data.get("action") or "").strip(),
            params=dict(data.get("params") or {}),
            depends_on=deps,
            requires_approval=bool(data.get("requires_approval", False)),
            idempotent=bool(data.get("idempotent", False)),
            max_retries=max(1, int(data.get("max_retries", 1) or 1)),
        )


@dataclass
class StepRecord:
    step_id: str
    status: str = StepStatus.PENDING.value
    attempts: int = 0
    approved: bool | None = None
    approval_note: str = ""
    output: Any = None
    receipt: dict[str, Any] | None = None
    verified: bool = False
    receipt_source: str = ""
    error: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepRecord":
        return cls(
            step_id=str(data["step_id"]),
            status=str(data.get("status", StepStatus.PENDING.value)),
            attempts=int(data.get("attempts", 0) or 0),
            approved=data.get("approved"),
            approval_note=str(data.get("approval_note") or ""),
            output=data.get("output"),
            receipt=data.get("receipt") if isinstance(data.get("receipt"), dict) else None,
            verified=bool(data.get("verified", False)),
            receipt_source=str(data.get("receipt_source") or ""),
            error=str(data.get("error") or ""),
            updated_at=float(data.get("updated_at") or 0.0),
        )


@dataclass
class WorkflowRun:
    run_id: str
    name: str
    status: str
    steps: list[WorkflowStep]
    records: dict[str, StepRecord]
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
    error: str = ""

    def next_ready_steps(self) -> list[WorkflowStep]:
        ready: list[WorkflowStep] = []
        for step in self.steps:
            rec = self.records.get(step.id)
            if rec is None or rec.status not in {StepStatus.PENDING.value, StepStatus.WAITING_APPROVAL.value}:
                continue
            if all(
                self.records.get(dep) is not None and self.records[dep].status == StepStatus.COMPLETED.value
                for dep in step.depends_on
            ):
                ready.append(step)
        return ready

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for rec in self.records.values():
            counts[rec.status] = counts.get(rec.status, 0) + 1
        return {
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "total_steps": len(self.steps),
            "counts": counts,
            "next_ready": [s.id for s in self.next_ready_steps()],
            "error": self.error or None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "context": dict(self.context),
            "steps": [
                {**step.to_dict(), "record": self.records[step.id].to_dict()}
                for step in self.steps
            ],
        }


def _validate_dag(steps: Sequence[WorkflowStep]) -> None:
    if not steps:
        raise WorkflowError("workflow must contain at least one step")
    ids: set[str] = set()
    for step in steps:
        if step.id in ids:
            raise WorkflowError(f"duplicate workflow step id: {step.id!r}")
        ids.add(step.id)
    by_id = {s.id: s for s in steps}
    for step in steps:
        for dep in step.depends_on:
            if dep not in by_id:
                raise WorkflowError(f"step {step.id!r} depends on unknown step {dep!r}")
    # Cycle detection (Kahn / DFS)
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(sid: str) -> None:
        if sid in visited:
            return
        if sid in visiting:
            raise WorkflowError(f"workflow dependency cycle detected at step {sid!r}")
        visiting.add(sid)
        for dep in by_id[sid].depends_on:
            _visit(dep)
        visiting.remove(sid)
        visited.add(sid)

    for step in steps:
        _visit(step.id)


class WorkflowEngine:
    """SQLite-persisted durable workflow runner."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    records_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _save(self, run: WorkflowRun) -> None:
        run.updated_at = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs
                    (run_id, name, status, steps_json, records_json, context_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    records_json=excluded.records_json,
                    context_json=excluded.context_json,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    run.run_id,
                    run.name,
                    run.status,
                    json.dumps([s.to_dict() for s in run.steps], ensure_ascii=False),
                    json.dumps({k: v.to_dict() for k, v in run.records.items()}, ensure_ascii=False),
                    json.dumps(run.context, ensure_ascii=False, default=str),
                    run.error,
                    run.created_at,
                    run.updated_at,
                ),
            )
            conn.commit()

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> WorkflowRun:
        steps = [WorkflowStep.from_dict(s) for s in json.loads(row["steps_json"])]
        raw_recs = json.loads(row["records_json"])
        records = {k: StepRecord.from_dict(v) for k, v in raw_recs.items()}
        context = json.loads(row["context_json"])
        return WorkflowRun(
            run_id=row["run_id"],
            name=row["name"],
            status=row["status"],
            steps=steps,
            records=records,
            context=context if isinstance(context, dict) else {},
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            error=str(row["error"] or ""),
        )

    def create_run(
        self,
        name: str,
        steps: Sequence[WorkflowStep | dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> WorkflowRun:
        parsed = [s if isinstance(s, WorkflowStep) else WorkflowStep.from_dict(s) for s in steps]
        _validate_dag(parsed)
        now = time.time()
        rid = (run_id or f"wf_{uuid.uuid4().hex[:12]}").strip()
        records = {
            s.id: StepRecord(step_id=s.id, status=StepStatus.PENDING.value, updated_at=now)
            for s in parsed
        }
        run = WorkflowRun(
            run_id=rid,
            name=str(name or rid).strip(),
            status=StepStatus.PENDING.value,
            steps=parsed,
            records=records,
            context=dict(context or {}),
            created_at=now,
            updated_at=now,
        )
        self._save(run)
        return run

    def get_run(self, run_id: str) -> WorkflowRun | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row is not None else None

    def list_runs(self, *, status: str | None = None, limit: int = 20) -> list[WorkflowRun]:
        cap = max(1, min(100, int(limit or 20)))
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM workflow_runs WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, cap),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
                    (cap,),
                ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def _recompute_status(self, run: WorkflowRun) -> None:
        statuses = {rec.status for rec in run.records.values()}
        if StepStatus.OUTCOME_UNKNOWN.value in statuses:
            run.status = StepStatus.OUTCOME_UNKNOWN.value
        elif StepStatus.FAILED.value in statuses:
            run.status = StepStatus.FAILED.value
        elif StepStatus.WAITING_APPROVAL.value in statuses:
            run.status = StepStatus.WAITING_APPROVAL.value
        elif statuses <= {StepStatus.COMPLETED.value, StepStatus.SKIPPED.value}:
            run.status = StepStatus.COMPLETED.value
        elif StepStatus.RUNNING.value in statuses:
            run.status = StepStatus.RUNNING.value
        else:
            run.status = StepStatus.PENDING.value

    def reconcile_interrupted(self, run_id: str) -> WorkflowRun:
        """Recover steps left in ``running`` after a process crash/restart.

        Idempotent steps safely reset to ``pending`` for resume; non-idempotent
        steps fail closed to ``outcome_unknown`` so side effects are never
        blindly replayed without explicit reconciliation.
        """
        with self._lock:
            run = self.get_run(run_id)
            if run is None:
                raise WorkflowError(f"unknown workflow run: {run_id!r}")
            changed = False
            by_id = {s.id: s for s in run.steps}
            now = time.time()
            for sid, rec in run.records.items():
                if rec.status != StepStatus.RUNNING.value:
                    continue
                step = by_id.get(sid)
                changed = True
                rec.updated_at = now
                if step is not None and step.idempotent:
                    rec.status = StepStatus.PENDING.value
                    rec.attempts = max(0, rec.attempts - 1)
                    rec.error = "interrupted while running; reset for idempotent retry"
                else:
                    rec.status = StepStatus.OUTCOME_UNKNOWN.value
                    rec.error = (
                        "interrupted while executing non-idempotent step; "
                        "reconcile external state before replaying"
                    )
                    run.error = f"step {sid!r} outcome unknown after interruption"
            if changed:
                self._recompute_status(run)
                self._save(run)
            return run

    def approve_step(self, run_id: str, step_id: str, *, approved: bool = True, note: str = "") -> WorkflowRun:
        with self._lock:
            run = self.get_run(run_id)
            if run is None:
                raise WorkflowError(f"unknown workflow run: {run_id!r}")
            rec = run.records.get(step_id)
            if rec is None:
                raise WorkflowError(f"unknown step {step_id!r} in run {run_id!r}")
            rec.approved = bool(approved)
            rec.approval_note = str(note or "")
            rec.updated_at = time.time()
            if approved:
                if rec.status == StepStatus.WAITING_APPROVAL.value:
                    rec.status = StepStatus.PENDING.value
            else:
                rec.status = StepStatus.FAILED.value
                rec.error = f"approval denied{f': {note}' if note else ''}"
                run.error = rec.error
            self._recompute_status(run)
            self._save(run)
            return run

    def checkpoint_step(
        self,
        run_id: str,
        step_id: str,
        *,
        status: str = StepStatus.COMPLETED.value,
        output: Any = None,
        error: str = "",
        receipt: dict[str, Any] | None = None,
        receipt_source: str = "self_reported",
    ) -> WorkflowRun:
        """Persist a step result with explicit receipt/verification provenance.

        A self-reported ``completed`` checkpoint without a structured tool
        receipt is stored with ``verified=False`` so callers never mistake a
        model-authored checklist update for proven external execution.
        """
        valid = {s.value for s in StepStatus}
        if status not in valid:
            raise WorkflowError(f"invalid step status {status!r}; expected one of {sorted(valid)}")
        with self._lock:
            run = self.get_run(run_id)
            if run is None:
                raise WorkflowError(f"unknown workflow run: {run_id!r}")
            rec = run.records.get(step_id)
            if rec is None:
                raise WorkflowError(f"unknown step {step_id!r} in run {run_id!r}")
            rec.status = status
            rec.attempts = max(1, rec.attempts)
            if output is not None:
                rec.output = output
            if receipt is not None and isinstance(receipt, dict) and receipt:
                rec.receipt = dict(receipt)
                rec.receipt_source = str(receipt_source or "tool_receipt")
                rec.verified = bool(receipt.get("ok", True)) and rec.receipt_source != "self_reported"
            else:
                rec.receipt_source = str(receipt_source or "self_reported")
                rec.verified = False
            if error:
                rec.error = str(error)
                if status in {StepStatus.FAILED.value, StepStatus.OUTCOME_UNKNOWN.value}:
                    run.error = rec.error
            elif status == StepStatus.COMPLETED.value:
                rec.error = ""
            rec.updated_at = time.time()
            self._recompute_status(run)
            self._save(run)
            return run

    def advance(
        self,
        run_id: str,
        executor: Callable[[WorkflowStep, dict[str, Any]], Any],
    ) -> WorkflowRun:
        """Execute ready steps in topological order until completion, failure, or an approval gate."""
        with self._lock:
            run = self.reconcile_interrupted(run_id)
            if run.status in {
                StepStatus.COMPLETED.value,
                StepStatus.FAILED.value,
                StepStatus.OUTCOME_UNKNOWN.value,
            }:
                return run

            run.status = StepStatus.RUNNING.value
            self._save(run)

            while True:
                ready = run.next_ready_steps()
                if not ready:
                    break
                progressed = False
                for step in ready:
                    rec = run.records[step.id]
                    if step.requires_approval and rec.approved is not True:
                        rec.status = StepStatus.WAITING_APPROVAL.value
                        rec.updated_at = time.time()
                        run.status = StepStatus.WAITING_APPROVAL.value
                        self._save(run)
                        return run

                    max_tries = step.max_retries if step.idempotent else 1
                    rec.status = StepStatus.RUNNING.value
                    rec.updated_at = time.time()
                    self._save(run)

                    succeeded = False
                    last_err = ""
                    while rec.attempts < max_tries:
                        rec.attempts += 1
                        try:
                            step_ctx = {
                                **run.context,
                                "outputs": {
                                    sid: r.output
                                    for sid, r in run.records.items()
                                    if r.status == StepStatus.COMPLETED.value
                                },
                            }
                            rec.output = executor(step, step_ctx)
                            rec.status = StepStatus.COMPLETED.value
                            rec.error = ""
                            rec.updated_at = time.time()
                            succeeded = True
                            progressed = True
                            break
                        except Exception as exc:  # noqa: BLE001
                            last_err = f"{type(exc).__name__}: {exc}"
                            rec.error = last_err
                            rec.updated_at = time.time()
                            self._save(run)

                    if not succeeded:
                        rec.status = StepStatus.FAILED.value
                        rec.error = last_err or "step failed"
                        run.error = f"step {step.id!r} failed: {rec.error}"
                        run.status = StepStatus.FAILED.value
                        self._save(run)
                        return run
                    self._save(run)
                if not progressed:
                    break

            self._recompute_status(run)
            self._save(run)
            return run
