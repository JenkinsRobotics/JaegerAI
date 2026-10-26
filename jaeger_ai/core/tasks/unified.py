"""Unified Scheduler — bridges legacy CronRunner and DurableTaskManager.

This is the single entry point for all scheduling in JaegerAI:

- **Cron-style scheduling** (from legacy `CronRunner`) — periodic prompts
- **Durable tasks** (from `GatewayTaskOwner`) — one-shot or long-running work
- **Kanban board** (from legacy `Board`) — task management

Usage:
    ```python
    from jaeger_ai.core.tasks.unified import UnifiedScheduler

    scheduler = UnifiedScheduler()

    # Cron-style scheduling
    task = scheduler.schedule_cron("0 9 * * *", "Morning briefing", name="daily-brief")
    scheduler.cancel_cron("daily-brief")
    jobs = scheduler.list_cron()

    # Durable tasks
    task = scheduler.submit("Research AI papers", context={"topic": "agents"})

    # Kanban board
    card = scheduler.add_card("Fix login bug", column="backlog")
    scheduler.move_card(card.id, "in_progress")
    ```

The unified scheduler automatically:
- Routes cron jobs to the legacy `CronRunner` (backward compatible)
- Stores all tasks in the new `SqliteDurableTaskStore`
- Provides a single API for both systems
- Handles migration from legacy schedules on first use
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import logging
import threading
import time
import uuid

from .models import DurableTask, TaskKind, TaskState
from .store import SqliteDurableTaskStore

logger = logging.getLogger(__name__)

# Columns for the kanban board
BOARD_COLUMNS = ("backlog", "ready", "in_progress", "blocked", "done")


@dataclass
class TaskCard:
    """A card on the kanban board."""
    card_id: str
    title: str
    column: str = "backlog"
    source: str = "manual"
    assignee: str = ""
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "title": self.title,
            "column": self.column,
            "source": self.source,
            "assignee": self.assignee,
            "priority": self.priority,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


class UnifiedScheduler:
    """Single scheduler combining cron, durable tasks, and kanban board.

    This is the recommended interface for all scheduling in JaegerAI.
    It wraps both the legacy CronRunner and the new DurableTaskManager,
    providing a unified API while maintaining backward compatibility.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        cron_callback: Callable[..., Any] | None = None,
        *,
        enable_legacy_cron: bool = True,
    ) -> None:
        """Initialize the unified scheduler.

        Args:
            db_path: Path to SQLite database for durable tasks
            cron_callback: Callback for cron job execution (legacy)
            enable_legacy_cron: Whether to enable the legacy CronRunner
        """
        if db_path is None:
            db_path = Path.home() / ".jaeger" / "gateway_sessions.sqlite3"

        self.db_path = db_path
        self.store = SqliteDurableTaskStore(db_path)
        self._cron_callback = cron_callback
        self._enable_legacy_cron = enable_legacy_cron
        self._cron_runner = None
        self._lock = threading.Lock()

        # Kanban board state (in-memory, persisted to SQLite)
        self._cards: dict[str, TaskCard] = {}
        self._load_cards()

    # ─────────────────────────────────────────────────────────────
    # Cron-style scheduling (wraps legacy CronRunner)
    # ─────────────────────────────────────────────────────────────

    def schedule_cron(
        self,
        cron_expr: str,
        prompt: str,
        name: str | None = None,
        *,
        owning_agent: str = "jaeger",
    ) -> DurableTask:
        """Schedule a recurring cron job.

        This creates a durable task AND registers it with the legacy
        CronRunner for backward compatibility.

        Args:
            cron_expr: Cron expression (e.g., "0 9 * * *") or interval ("300s", "@hourly")
            prompt: The prompt to execute
            name: Optional name for the job
            owning_agent: Agent that owns this task

        Returns:
            The created DurableTask
        """
        task_name = name or f"cron-{uuid.uuid4().hex[:8]}"

        # Create durable task record
        task = DurableTask(
            task_id=f"cron:{task_name}",
            owning_agent=owning_agent,
            goal=prompt,
            kind=TaskKind.SCHEDULED_JOB,
            state=TaskState.QUEUED,
            payload={
                "cron_expr": cron_expr,
                "prompt": prompt,
                "name": task_name,
                "legacy_compatible": True,
            },
        )
        task.next_execution = self._next_cron_time(cron_expr)
        self.store.save_task(task)

        # Register with legacy CronRunner if enabled
        if self._enable_legacy_cron:
            self._register_legacy_cron(task_name, cron_expr, prompt)

        logger.info(f"Scheduled cron job '{task_name}': {cron_expr}")
        return task

    def cancel_cron(self, name: str) -> bool:
        """Cancel a cron job by name.

        Args:
            name: The job name

        Returns:
            True if cancelled, False if not found
        """
        task_id = f"cron:{name}"
        task = self.store.get_task(task_id)
        if task is None:
            return False

        # Cancel in durable store
        task.state = TaskState.CANCELLED
        task.cancellation = "user requested"
        self.store.save_task(task)

        # Cancel in legacy system
        if self._enable_legacy_cron:
            self._unregister_legacy_cron(name)

        logger.info(f"Cancelled cron job '{name}'")
        return True

    def list_cron(self, owning_agent: str | None = None) -> list[DurableTask]:
        """List all scheduled cron jobs.

        Args:
            owning_agent: Filter by owning agent (optional)

        Returns:
            List of scheduled tasks
        """
        tasks = self.store.list_tasks(kind=TaskKind.SCHEDULED_JOB)
        if owning_agent:
            tasks = [t for t in tasks if t.owning_agent == owning_agent]
        # Only return active (non-terminal) tasks
        return [t for t in tasks if not t.is_terminal]

    # ─────────────────────────────────────────────────────────────
    # Durable task submission (from GatewayTaskOwner)
    # ─────────────────────────────────────────────────────────────

    def submit(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        owning_agent: str = "jaeger",
        kind: TaskKind = TaskKind.BACKGROUND_WORK,
        **kwargs,
    ) -> DurableTask:
        """Submit a durable background task.

        Args:
            goal: What the task should accomplish
            context: Additional context for the task
            owning_agent: Agent that owns this task
            kind: Type of task
            **kwargs: Additional task options

        Returns:
            The created DurableTask
        """
        task = DurableTask(
            task_id=f"task:{uuid.uuid4().hex[:12]}",
            owning_agent=owning_agent,
            goal=goal,
            kind=kind,
            state=TaskState.QUEUED,
            payload=context or {},
        )
        self.store.save_task(task)
        logger.info(f"Submitted task {task.task_id}: {goal[:50]}...")
        return task

    def get_task(self, task_id: str) -> DurableTask | None:
        """Get a task by ID."""
        return self.store.get_task(task_id)

    def list_tasks(
        self,
        owning_agent: str | None = None,
        state: TaskState | None = None,
        kind: TaskKind | None = None,
    ) -> list[DurableTask]:
        """List tasks with optional filters."""
        return self.store.list_tasks(
            owning_agent=owning_agent,
            state=state,
            kind=kind,
        )

    def cancel_task(self, task_id: str, reason: str = "user requested") -> bool:
        """Cancel a task."""
        task = self.store.get_task(task_id)
        if task is None or task.is_terminal:
            return False
        task.state = TaskState.CANCELLED
        task.cancellation = reason
        self.store.save_task(task)
        return True

    # ─────────────────────────────────────────────────────────────
    # Kanban board (from legacy Board)
    # ─────────────────────────────────────────────────────────────

    def add_card(
        self,
        title: str,
        column: str = "backlog",
        *,
        source: str = "manual",
        assignee: str = "",
        priority: str = "normal",
        tags: list[str] | None = None,
    ) -> TaskCard:
        """Add a card to the kanban board.

        Args:
            title: Card title
            column: Column to add to (backlog, ready, in_progress, blocked, done)
            source: Where the card came from
            assignee: Who's assigned
            priority: Priority level
            tags: Optional tags

        Returns:
            The created TaskCard
        """
        if column not in BOARD_COLUMNS:
            raise ValueError(f"Invalid column '{column}'. Must be one of: {BOARD_COLUMNS}")

        card = TaskCard(
            card_id=f"card:{uuid.uuid4().hex[:8]}",
            title=title,
            column=column,
            source=source,
            assignee=assignee,
            priority=priority,
            tags=tags or [],
        )
        with self._lock:
            self._cards[card.card_id] = card
            self._save_cards()
        return card

    def get_card(self, card_id: str) -> TaskCard | None:
        """Get a card by ID."""
        return self._cards.get(card_id)

    def list_cards(
        self,
        column: str | None = None,
        assignee: str | None = None,
        tag: str | None = None,
    ) -> list[TaskCard]:
        """List cards with optional filters."""
        cards = list(self._cards.values())
        if column:
            cards = [c for c in cards if c.column == column]
        if assignee:
            cards = [c for c in cards if c.assignee == assignee]
        if tag:
            cards = [c for c in cards if tag in c.tags]
        return sorted(cards, key=lambda c: c.updated_at, reverse=True)

    def move_card(self, card_id: str, column: str) -> TaskCard | None:
        """Move a card to a different column."""
        if column not in BOARD_COLUMNS:
            raise ValueError(f"Invalid column '{column}'. Must be one of: {BOARD_COLUMNS}")

        card = self._cards.get(card_id)
        if card is None:
            return None

        card.column = column
        card.updated_at = time.time()
        with self._lock:
            self._save_cards()
        return card

    def update_card(self, card_id: str, **fields) -> TaskCard | None:
        """Update card fields."""
        card = self._cards.get(card_id)
        if card is None:
            return None

        for key, value in fields.items():
            if hasattr(card, key):
                setattr(card, key, value)
        card.updated_at = time.time()

        with self._lock:
            self._save_cards()
        return card

    def remove_card(self, card_id: str) -> bool:
        """Remove a card from the board."""
        with self._lock:
            if card_id in self._cards:
                del self._cards[card_id]
                self._save_cards()
                return True
        return False

    def board_summary(self) -> dict[str, int]:
        """Get counts per column."""
        summary = {col: 0 for col in BOARD_COLUMNS}
        for card in self._cards.values():
            summary[card.column] = summary.get(card.column, 0) + 1
        return summary

    # ─────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler (begins cron polling)."""
        if self._enable_legacy_cron and self._cron_callback and self._cron_runner is None:
            from jaeger_agent.background.cron_runner import CronRunner
            self._cron_runner = CronRunner(self._cron_callback, llm_lock=None)
            self._cron_runner.start()
            logger.info("Unified scheduler started (legacy cron enabled)")

    def shutdown(self) -> None:
        """Shut down the scheduler."""
        if self._cron_runner is not None:
            self._cron_runner.shutdown()
            self._cron_runner = None
            logger.info("Unified scheduler shut down")

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    def _next_cron_time(self, cron_expr: str) -> float | None:
        """Calculate next execution time for a cron expression."""
        try:
            from croniter import croniter
            from datetime import datetime, timezone
            base = datetime.now(timezone.utc)
            return croniter(cron_expr, base).get_next(float)
        except Exception:
            # Handle simple intervals like "300s" or "@hourly"
            try:
                if cron_expr.startswith("@"):
                    # @hourly, @daily, etc.
                    intervals = {"@hourly": 3600, "@daily": 86400, "@weekly": 604800}
                    return time.time() + intervals.get(cron_expr, 3600)
                elif cron_expr.endswith("s"):
                    return time.time() + float(cron_expr[:-1])
                elif cron_expr.endswith("m"):
                    return time.time() + float(cron_expr[:-1]) * 60
                elif cron_expr.endswith("h"):
                    return time.time() + float(cron_expr[:-1]) * 3600
            except Exception:
                pass
            return None

    def _register_legacy_cron(self, name: str, cron_expr: str, prompt: str) -> None:
        """Register a cron job with the legacy system."""
        try:
            from jaeger_agent.memory import memory as mem
            mem.add_schedule(cron_expr=cron_expr, prompt=prompt, name=name)
        except Exception as exc:
            logger.warning(f"Failed to register legacy cron '{name}': {exc}")

    def _unregister_legacy_cron(self, name: str) -> None:
        """Unregister a cron job from the legacy system."""
        try:
            from jaeger_agent.memory import memory as mem
            mem.cancel_schedule(name)
        except Exception as exc:
            logger.warning(f"Failed to unregister legacy cron '{name}': {exc}")

    def _load_cards(self) -> None:
        """Load cards from SQLite."""
        try:
            import sqlite3
            import json
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Create table if not exists
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS task_cards (
                        card_id TEXT PRIMARY KEY,
                        card_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                rows = conn.execute("SELECT card_json FROM task_cards").fetchall()
                for row in rows:
                    data = json.loads(row["card_json"])
                    card = TaskCard(**data)
                    self._cards[card.card_id] = card
        except Exception as exc:
            logger.warning(f"Failed to load cards: {exc}")

    def _save_cards(self) -> None:
        """Save cards to SQLite."""
        try:
            import sqlite3
            import json
            with sqlite3.connect(self.db_path) as conn:
                # Create table if not exists
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS task_cards (
                        card_id TEXT PRIMARY KEY,
                        card_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                for card in self._cards.values():
                    conn.execute(
                        """
                        INSERT INTO task_cards (card_id, card_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(card_id) DO UPDATE SET
                            card_json=excluded.card_json,
                            updated_at=excluded.updated_at
                        """,
                        (
                            card.card_id,
                            json.dumps(card.to_dict()),
                            card.created_at,
                            card.updated_at,
                        ),
                    )
        except Exception as exc:
            logger.warning(f"Failed to save cards: {exc}")


__all__ = ["UnifiedScheduler", "TaskCard", "BOARD_COLUMNS"]
