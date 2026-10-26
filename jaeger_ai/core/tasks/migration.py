"""Migration bridge — imports legacy schedules and board into unified system.

This module handles one-time migration from the legacy scheduler to the
unified scheduler. It runs automatically on first boot after upgrade.

Migration sources:
- Legacy `schedules` table (SQLite in instance memory) → `durable_tasks`
- Legacy `board.json` (JSON file) → `task_cards` table

The migration is:
- **Idempotent** — safe to run multiple times
- **Non-destructive** — legacy data is preserved
- **Automatic** — runs on scheduler initialization if needed
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import logging
import sqlite3
import time

from .models import DurableTask, TaskKind, TaskState
from .store import SqliteDurableTaskStore
from .unified import UnifiedScheduler, TaskCard

logger = logging.getLogger(__name__)


def migrate_legacy_schedules(
    store: SqliteDurableTaskStore,
    instance_memory_dir: Path,
    *,
    owning_agent: str = "jaeger",
) -> int:
    """Migrate legacy schedules from instance memory to durable tasks.

    Reads from: `<instance_memory_dir>/state.db` (table: `schedules`)
    Writes to: `store` (table: `durable_tasks`)

    Args:
        store: The durable task store to write to
        instance_memory_dir: Path to instance memory directory
        owning_agent: Agent to assign migrated tasks to

    Returns:
        Number of schedules migrated
    """
    legacy_db = instance_memory_dir / "state.db"
    if not legacy_db.exists():
        logger.info("No legacy schedules database found — nothing to migrate")
        return 0

    migrated = 0
    try:
        with sqlite3.connect(legacy_db) as conn:
            conn.row_factory = sqlite3.Row
            # Check if schedules table exists
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schedules'"
            ).fetchall()
            if not tables:
                logger.info("No legacy schedules table — nothing to migrate")
                return 0

            rows = conn.execute("SELECT * FROM schedules").fetchall()
            for row in rows:
                schedule = dict(row)

                # Skip if already migrated
                task_id = f"cron:{schedule.get('name', 'unknown')}"
                existing = store.get_task(task_id)
                if existing is not None:
                    logger.debug(f"Schedule '{task_id}' already migrated — skipping")
                    continue

                # Create durable task from legacy schedule
                task = DurableTask(
                    task_id=task_id,
                    owning_agent=owning_agent,
                    goal=schedule.get("prompt", ""),
                    kind=TaskKind.SCHEDULED_JOB,
                    state=TaskState.QUEUED,
                    payload={
                        "cron_expr": schedule.get("cron_expr", schedule.get("schedule", "")),
                        "prompt": schedule.get("prompt", ""),
                        "name": schedule.get("name", ""),
                        "enabled": schedule.get("enabled", True),
                        "migrated_from": "legacy_schedules",
                        "legacy_id": schedule.get("id"),
                    },
                    created_at=float(schedule.get("created_at", time.time())),
                )
                store.save_task(task)
                migrated += 1
                logger.info(f"Migrated legacy schedule: {task_id}")

    except Exception as exc:
        logger.error(f"Failed to migrate legacy schedules: {exc}")

    logger.info(f"Migrated {migrated} legacy schedules")
    return migrated


def migrate_legacy_board(
    scheduler: UnifiedScheduler,
    instance_memory_dir: Path,
) -> int:
    """Migrate legacy board.json to task cards.

    Reads from: `<instance_memory_dir>/board.json`
    Writes to: `task_cards` table via scheduler

    Args:
        scheduler: The unified scheduler
        instance_memory_dir: Path to instance memory directory

    Returns:
        Number of cards migrated
    """
    board_file = instance_memory_dir / "board.json"
    if not board_file.exists():
        logger.info("No legacy board.json found — nothing to migrate")
        return 0

    migrated = 0
    try:
        data = json.loads(board_file.read_text(encoding="utf-8"))
        cards = data.get("cards", data if isinstance(data, list) else [])

        for card_data in cards:
            # Skip if already migrated (check by title + source)
            existing = [
                c for c in scheduler.list_cards()
                if c.title == card_data.get("title", "")
                and c.metadata.get("migrated_from") == "legacy_board"
            ]
            if existing:
                continue

            card = scheduler.add_card(
                title=card_data.get("title", "Untitled"),
                column=card_data.get("column", "backlog"),
                source=card_data.get("source", "migrated"),
                assignee=card_data.get("assignee", ""),
                priority=card_data.get("priority", "normal"),
                tags=card_data.get("tags", []),
            )
            # Mark as migrated
            scheduler.update_card(card.card_id, metadata={"migrated_from": "legacy_board"})
            migrated += 1
            logger.info(f"Migrated board card: {card.title}")

    except Exception as exc:
        logger.error(f"Failed to migrate legacy board: {exc}")

    logger.info(f"Migrated {migrated} board cards")
    return migrated


def migrate_all(
    scheduler: UnifiedScheduler,
    instance_memory_dir: Path | None = None,
    *,
    owning_agent: str = "jaeger",
    force: bool = False,
) -> dict[str, int]:
    """Run all migrations from legacy systems.

    Args:
        scheduler: The unified scheduler
        instance_memory_dir: Path to instance memory (default: ~/.jaeger/instances/jaeger/memory)
        owning_agent: Agent to assign migrated tasks to
        force: Re-migrate even if already migrated

    Returns:
        Dictionary with migration counts: {"schedules": N, "board_cards": M}
    """
    if instance_memory_dir is None:
        instance_memory_dir = Path.home() / ".jaeger" / "instances" / owning_agent / "memory"

    results = {
        "schedules": 0,
        "board_cards": 0,
    }

    logger.info(f"Starting migration from {instance_memory_dir}")

    # Migrate schedules
    try:
        results["schedules"] = migrate_legacy_schedules(
            scheduler.store,
            instance_memory_dir,
            owning_agent=owning_agent,
        )
    except Exception as exc:
        logger.error(f"Schedule migration failed: {exc}")

    # Migrate board
    try:
        results["board_cards"] = migrate_legacy_board(
            scheduler,
            instance_memory_dir,
        )
    except Exception as exc:
        logger.error(f"Board migration failed: {exc}")

    # Mark migration as complete
    migration_flag = instance_memory_dir / ".migration_complete"
    if sum(results.values()) > 0 or force:
        try:
            migration_flag.write_text(
                json.dumps({"completed_at": time.time(), "results": results}),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Failed to write migration flag: {exc}")

    logger.info(f"Migration complete: {results}")
    return results


def needs_migration(instance_memory_dir: Path | None = None) -> bool:
    """Check if migration is needed.

    Args:
        instance_memory_dir: Path to instance memory

    Returns:
        True if migration has not been run
    """
    if instance_memory_dir is None:
        instance_memory_dir = Path.home() / ".jaeger" / "instances" / "jaeger" / "memory"

    migration_flag = instance_memory_dir / ".migration_complete"
    return not migration_flag.exists()


__all__ = [
    "migrate_legacy_schedules",
    "migrate_legacy_board",
    "migrate_all",
    "needs_migration",
]
