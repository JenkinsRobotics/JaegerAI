"""Deep Think — autonomous skill-development mode.

See docs/deep_think_design.md + docs/kanban_design.md. This module holds
the pure data layer:

  • DeepThinkTask   — one queued skill-development job
  • DeepThinkQueue  — a view over the kanban board: Deep Think jobs are
    board cards with ``source="deepthink"``
  • DeepThinkState  — in-process mode state (realtime ⇄ deep_think)

The Deep Think queue is no longer a separate file — it IS the board
(``<instance>/memory/board.json``), so a queued job shows up on the
``/board`` view alongside everything else. ``DeepThinkQueue`` keeps its
original API so the daemon, the work loop, and the TUI are unchanged.

The model SWAP itself (switch_model) and the work loop live in the
runtime/TUI layer — keeping this module import-clean (no dependency on
jaeger_os.main, so no circular import).

Locked design (2026-05-19):
  • Task source: BOTH — user-queued + agent-proposed (agent jobs need
    approval before they run).
  • Activation: BOTH — `/deepthink start` on demand + opt-in auto-idle.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from jaeger_os.agent.background.board import Board, board_for_layout


TaskStatus = Literal["pending", "in_progress", "done", "failed"]
TaskSource = Literal["user", "agent"]
Mode = Literal["realtime", "deep_think"]


# ── Task ────────────────────────────────────────────────────────────


@dataclass
class DeepThinkTask:
    """One skill-development job for Deep Think to work.

    ``approved`` gates agent-proposed jobs: a user-queued task is
    approved on creation; an agent-proposed task starts unapproved and
    only becomes eligible for the work loop once the user approves it."""

    description: str
    source: TaskSource = "user"
    id: str = field(default_factory=lambda: "dt_" + uuid.uuid4().hex[:8])
    status: TaskStatus = "pending"
    approved: bool = True
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: str = ""
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DeepThinkTask":
        # Tolerate extra/missing keys so an older queue file still loads.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# ── Queue — a view over the kanban board ────────────────────────────


# Deep Think status ⇄ board column. The board's single `column` axis
# carries both DeepThinkTask.status and DeepThinkTask.approved:
#   backlog      = pending  + unapproved   (awaiting the user)
#   ready        = pending  + approved     (eligible for the work loop)
#   in_progress  = in_progress
#   done         = done | failed           (failed carries a "failed" tag)
_DEEPTHINK_TAG = "deepthink"


class DeepThinkQueue:
    """The Deep Think task queue, backed by the kanban board.

    Each task is a board card tagged ``deepthink`` with
    ``source="deepthink"``. This class keeps the original queue API
    (``add`` / ``pending`` / ``next_pending`` / ``mark_*`` / ``approve``
    / ``summary`` …) so the work loop and TUI need no changes — only the
    storage moved from a private JSONL into the shared board."""

    def __init__(self, board: Board) -> None:
        self.board = board

    # ── card ⇄ task mapping ─────────────────────────────────────────

    @staticmethod
    def _to_task(card: Any) -> DeepThinkTask:
        if card.column in ("backlog", "ready", "blocked"):
            status: TaskStatus = "pending"
        elif card.column == "in_progress":
            status = "in_progress"
        else:  # done
            status = "failed" if "failed" in card.tags else "done"
        source: TaskSource = "agent" if card.created_by == "agent" else "user"
        return DeepThinkTask(
            description=card.title,
            source=source,
            id=card.id,
            status=status,
            approved=card.column != "backlog",
            created_at=card.created_at,
            started_at=card.started_at,
            finished_at=card.finished_at,
            result=card.result,
            attempts=card.attempts,
        )

    def _cards(self) -> list[Any]:
        return self.board.list(source="deepthink")

    # ── operations ──────────────────────────────────────────────────

    def add(
        self,
        description: str,
        *,
        source: TaskSource = "user",
        approved: bool | None = None,
    ) -> DeepThinkTask:
        """Queue a new task. User tasks are auto-approved (land in
        ``ready``); agent-proposed tasks default to unapproved (land in
        ``backlog``, awaiting ``/deepthink approve``)."""
        if approved is None:
            approved = source == "user"
        card = self.board.add(
            description.strip(),
            column="ready" if approved else "backlog",
            source="deepthink",
            created_by=source,
            tags=[_DEEPTHINK_TAG],
        )
        return self._to_task(card)

    def all_tasks(self) -> list[DeepThinkTask]:
        return [self._to_task(c) for c in self._cards()]

    def get(self, task_id: str) -> DeepThinkTask | None:
        card = self.board.get(task_id)
        return self._to_task(card) if card else None

    def pending(self, *, approved_only: bool = True) -> list[DeepThinkTask]:
        """Tasks eligible for the work loop, oldest first."""
        cols = ("ready",) if approved_only else ("backlog", "ready")
        out = [self._to_task(c) for c in self._cards() if c.column in cols]
        return sorted(out, key=lambda t: t.created_at)

    def next_pending(self) -> DeepThinkTask | None:
        """The oldest approved+pending task, or None when the queue is
        drained."""
        ready = self.pending(approved_only=True)
        return ready[0] if ready else None

    def update(self, task_id: str, **fields: Any) -> DeepThinkTask | None:
        """Patch a task by id. ``status`` / ``approved`` translate to a
        column move; other fields write through to the card."""
        card = self.board.get(task_id)
        if card is None:
            return None
        if "approved" in fields:
            if fields["approved"] and card.column == "backlog":
                self.board.move(task_id, "ready")
            elif not fields["approved"]:
                self.board.move(task_id, "backlog")
        if "status" in fields:
            self.board.move(task_id, _status_to_column(fields["status"]))
        passthrough = {k: v for k, v in fields.items()
                       if k in ("started_at", "finished_at", "result", "attempts")}
        if passthrough:
            self.board.update(task_id, **passthrough)
        return self.get(task_id)

    def mark_in_progress(self, task_id: str) -> DeepThinkTask | None:
        card = self.board.get(task_id)
        if card is None:
            return None
        self.board.move(task_id, "in_progress")
        self.board.update(task_id, attempts=card.attempts + 1)
        return self.get(task_id)

    def mark_done(self, task_id: str, result: str = "") -> DeepThinkTask | None:
        if self.board.get(task_id) is None:
            return None
        self.board.move(task_id, "done")
        self.board.update(task_id, result=result)
        return self.get(task_id)

    def mark_failed(self, task_id: str, result: str = "") -> DeepThinkTask | None:
        card = self.board.get(task_id)
        if card is None:
            return None
        self.board.move(task_id, "done")
        tags = card.tags if "failed" in card.tags else [*card.tags, "failed"]
        self.board.update(task_id, result=result, tags=tags)
        return self.get(task_id)

    def reset_in_progress(self) -> int:
        """Flip any ``in_progress`` Deep Think card back to ``ready`` —
        used when Deep Think is interrupted mid-task so the job is
        retried next idle window. Returns how many were reset."""
        n = 0
        for card in self._cards():
            if card.column == "in_progress":
                self.board.move(card.id, "ready")
                self.board.update(card.id, started_at=None)
                n += 1
        return n

    def approve(self, task_id: str) -> DeepThinkTask | None:
        card = self.board.get(task_id)
        if card is None:
            return None
        if card.column == "backlog":
            self.board.move(task_id, "ready")
        return self.get(task_id)

    def summary(self) -> dict[str, int]:
        """Counts by status — for the /deepthink status view."""
        tasks = self.all_tasks()
        out = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0,
               "awaiting_approval": 0, "total": len(tasks)}
        for task in tasks:
            out[task.status] = out.get(task.status, 0) + 1
            if task.status == "pending" and not task.approved:
                out["awaiting_approval"] += 1
        return out


def _status_to_column(status: str) -> str:
    return {
        "pending": "ready", "in_progress": "in_progress",
        "done": "done", "failed": "done",
    }.get(status, "ready")


# ── In-process mode state ───────────────────────────────────────────


@dataclass
class DeepThinkState:
    """Live mode state for the running process. The queue is on the
    board; this is the ephemeral 'which model is loaded / are we
    dreaming' state. Owned by the TUI / runtime, not persisted."""

    mode: Mode = "realtime"
    realtime_model: str = "gemma-4-26b-a4b-it-q4_k_m"
    coder_model: str = "qwen3-coder-30b-a3b-q4_k_m"
    entered_at: float | None = None
    current_task_id: str | None = None
    tasks_completed_this_session: int = 0

    def elapsed_s(self) -> float:
        return time.time() - self.entered_at if self.entered_at else 0.0


# ── Construction + one-time migration ───────────────────────────────


def _migrate_legacy_queue(layout: Any, board: Board) -> None:
    """One-time: fold a pre-board ``deep_think_queue.jsonl`` into the
    board, then rename it aside so the migration never runs twice."""
    legacy = layout.memory_dir / "deep_think_queue.jsonl"
    if not legacy.is_file():
        return
    for line in legacy.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            task = DeepThinkTask.from_dict(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
        column = "backlog" if not task.approved else _status_to_column(task.status)
        tags = [_DEEPTHINK_TAG] + (["failed"] if task.status == "failed" else [])
        board.add(
            task.description, column=column, source="deepthink",
            created_by=task.source, tags=tags,
        )
    legacy.rename(legacy.with_suffix(".jsonl.migrated"))


def queue_for_layout(layout: Any) -> DeepThinkQueue:
    """The Deep Think queue for an instance — a view over the instance's
    kanban board. Migrates a legacy JSONL queue on first call."""
    board = board_for_layout(layout)
    _migrate_legacy_queue(layout, board)
    return DeepThinkQueue(board)
