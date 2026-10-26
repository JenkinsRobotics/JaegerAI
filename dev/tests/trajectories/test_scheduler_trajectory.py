"""Trajectory tests for scheduler and task execution.

Tests the full flow of scheduling, executing, and completing tasks
with scripted (deterministic) responses.
"""

from __future__ import annotations

from pathlib import Path
import pytest


class TestSchedulerTrajectories:
    """Test complete scheduler workflows."""

    @pytest.fixture
    def scheduler(self, tmp_path):
        """Create a unified scheduler in a temp directory."""
        from jaeger_ai.core.tasks.unified import UnifiedScheduler
        db_path = tmp_path / "trajectory_test.db"
        return UnifiedScheduler(db_path=db_path, enable_legacy_cron=False)

    def test_cron_job_lifecycle(self, scheduler):
        """Complete lifecycle: schedule → list → cancel."""
        # Schedule a cron job
        task = scheduler.schedule_cron(
            cron_expr="0 9 * * *",
            prompt="Morning briefing",
            name="daily-brief",
        )
        assert task is not None
        assert task.task_id == "cron:daily-brief"
        assert task.payload["name"] == "daily-brief"
        assert task.payload["prompt"] == "Morning briefing"

        # List cron jobs
        jobs = scheduler.list_cron()
        assert len(jobs) == 1
        assert jobs[0].task_id == "cron:daily-brief"

        # Cancel
        assert scheduler.cancel_cron("daily-brief") is True
        jobs = scheduler.list_cron()
        assert len(jobs) == 0  # Cancelled tasks not listed

        # Try to cancel again (should fail)
        assert scheduler.cancel_cron("daily-brief") is False

    def test_durable_task_lifecycle(self, scheduler):
        """Complete lifecycle: submit → get → list → cancel."""
        # Submit a task
        task = scheduler.submit(
            "Research AI papers",
            context={"topic": "agent architectures"},
        )
        assert task is not None
        assert task.goal == "Research AI papers"
        assert task.payload["topic"] == "agent architectures"

        # Get the task
        retrieved = scheduler.get_task(task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == task.task_id

        # List tasks
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1

        # Cancel
        assert scheduler.cancel_task(task.task_id) is True
        retrieved = scheduler.get_task(task.task_id)
        assert retrieved is not None  # Still exists but cancelled

    def test_kanban_board_workflow(self, scheduler):
        """Complete kanban workflow: create → move through columns → complete."""
        # Create card in backlog
        card = scheduler.add_card("Implement feature X", column="backlog")
        assert card.column == "backlog"

        # Move to ready
        card = scheduler.move_card(card.card_id, "ready")
        assert card.column == "ready"

        # Move to in_progress
        card = scheduler.move_card(card.card_id, "in_progress")
        assert card.column == "in_progress"

        # Move to done
        card = scheduler.move_card(card.card_id, "done")
        assert card.column == "done"

        # Verify in summary
        summary = scheduler.board_summary()
        assert summary["done"] == 1
        assert summary["backlog"] == 0

    def test_multiple_tasks_isolation(self, scheduler):
        """Tasks for different agents are isolated."""
        # Create tasks for different agents
        task1 = scheduler.submit("Task for agent A", owning_agent="agent-a")
        task2 = scheduler.submit("Task for agent B", owning_agent="agent-b")

        # List all
        all_tasks = scheduler.list_tasks()
        assert len(all_tasks) == 2

        # Filter by agent
        agent_a_tasks = scheduler.list_tasks(owning_agent="agent-a")
        assert len(agent_a_tasks) == 1
        assert agent_a_tasks[0].owning_agent == "agent-a"

        agent_b_tasks = scheduler.list_tasks(owning_agent="agent-b")
        assert len(agent_b_tasks) == 1
        assert agent_b_tasks[0].owning_agent == "agent-b"


class TestMigrationTrajectories:
    """Test migration workflows."""

    def test_migration_idempotency(self, tmp_path):
        """Running migration twice doesn't duplicate data."""
        from jaeger_ai.core.tasks.unified import UnifiedScheduler
        from jaeger_ai.core.tasks.migration import migrate_all

        db_path = tmp_path / "migration_test.db"
        scheduler = UnifiedScheduler(db_path=db_path, enable_legacy_cron=False)

        # Create fake legacy data
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)

        # Run migration twice
        result1 = migrate_all(scheduler, memory_dir)
        result2 = migrate_all(scheduler, memory_dir)

        # Second run should migrate 0 items (already migrated)
        assert result2["schedules"] == 0
        assert result2["board_cards"] == 0

    def test_migration_with_existing_data(self, tmp_path):
        """Migration handles existing legacy data correctly."""
        from jaeger_ai.core.tasks.unified import UnifiedScheduler
        from jaeger_ai.core.tasks.migration import migrate_all
        import json
        import sqlite3

        # Create legacy database with schedules
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        legacy_db = memory_dir / "state.db"

        with sqlite3.connect(legacy_db) as conn:
            conn.execute("""
                CREATE TABLE schedules (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    cron_expr TEXT,
                    prompt TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at REAL
                )
            """)
            conn.execute(
                "INSERT INTO schedules (name, cron_expr, prompt, created_at) VALUES (?, ?, ?, ?)",
                ("test-job", "0 8 * * *", "Good morning", 1234567890.0),
            )

        # Create legacy board
        board_file = memory_dir / "board.json"
        board_file.write_text(json.dumps({
            "cards": [
                {"title": "Legacy task 1", "column": "backlog"},
                {"title": "Legacy task 2", "column": "in_progress"},
            ]
        }))

        # Run migration
        db_path = tmp_path / "migration_target.db"
        scheduler = UnifiedScheduler(db_path=db_path, enable_legacy_cron=False)
        result = migrate_all(scheduler, memory_dir)

        assert result["schedules"] == 1
        assert result["board_cards"] == 2

        # Verify migrated data
        cron_jobs = scheduler.list_cron()
        assert len(cron_jobs) == 1
        assert cron_jobs[0].payload["name"] == "test-job"

        cards = scheduler.list_cards()
        assert len(cards) == 2


class TestTaskExecutionTrajectory:
    """Test task execution flow (simulated)."""

    def test_task_state_progression(self, tmp_path):
        """Tasks progress through states correctly."""
        from jaeger_ai.core.tasks.models import DurableTask, TaskKind, TaskState
        from jaeger_ai.core.tasks.store import SqliteDurableTaskStore

        store = SqliteDurableTaskStore(tmp_path / "exec_test.db")

        # Create task
        task = DurableTask(
            task_id="exec:test-1",
            owning_agent="jaeger",
            goal="Execute this task",
        )
        assert task.state == TaskState.QUEUED
        store.save_task(task)

        # Start execution
        task.state = TaskState.RUNNING
        store.save_task(task)
        retrieved = store.get_task(task.task_id)
        assert retrieved.state == TaskState.RUNNING

        # Complete
        task.state = TaskState.COMPLETED
        task.result = {"output": "success"}
        store.save_task(task)
        retrieved = store.get_task(task.task_id)
        assert retrieved.state == TaskState.COMPLETED
        assert retrieved.is_terminal


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
