"""Property-based tests for task and scheduler invariants.

Uses Hypothesis to auto-generate test cases and verify that
invariants hold across all inputs.

Run with: pytest dev/tests/properties/ -v
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

# Try to import hypothesis
try:
    from hypothesis import given, strategies as st, settings, HealthCheck
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False
    # Create dummy decorators if hypothesis not available
    def given(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def settings(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    class st:
        @staticmethod
        def text(*args, **kwargs): return None
        @staticmethod
        def integers(*args, **kwargs): return None
        @staticmethod
        def lists(*args, **kwargs): return None
        @staticmethod
        def one_of(*args, **kwargs): return None


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    return tmp_path / "test_tasks.db"


class TestTaskStoreProperties:
    """Property-based tests for task store invariants."""

    @pytest.mark.skipif(not HAS_HYPOTHESIS, reason="Hypothesis not installed")
    @given(
        task_id=st.text(min_size=1, max_size=100),
        goal=st.text(min_size=1, max_size=500),
        agent=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=50, suppress_health_check=list(HealthCheck))
    def test_task_roundtrip(self, temp_db, task_id, goal, agent):
        """Any task saved can be retrieved with the same data."""
        from jaeger_ai.core.tasks.models import DurableTask, TaskKind, TaskState
        from jaeger_ai.core.tasks.store import SqliteDurableTaskStore

        store = SqliteDurableTaskStore(temp_db)

        # Create and save task
        task = DurableTask(
            task_id=f"test:{task_id}",
            owning_agent=agent,
            goal=goal,
            kind=TaskKind.BACKGROUND_WORK,
        )
        store.save_task(task)

        # Retrieve and verify
        retrieved = store.get_task(task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == task.task_id
        assert retrieved.goal == goal
        assert retrieved.owning_agent == agent
        assert retrieved.kind == TaskKind.BACKGROUND_WORK

    @pytest.mark.skipif(not HAS_HYPOTHESIS, reason="Hypothesis not installed")
    @given(
        task_id=st.text(min_size=1, max_size=50),
        updates=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=20)
    def test_task_update_idempotency(self, temp_db, task_id, updates):
        """Updating a task multiple times with same data is idempotent."""
        from jaeger_ai.core.tasks.models import DurableTask, TaskKind, TaskState
        from jaeger_ai.core.tasks.store import SqliteDurableTaskStore

        store = SqliteDurableTaskStore(temp_db)

        task = DurableTask(
            task_id=f"test:{task_id}",
            owning_agent="test-agent",
            goal="Test goal",
        )
        store.save_task(task)

        # Update multiple times with same state
        for _ in range(updates):
            task.state = TaskState.RUNNING
            store.save_task(task)

        retrieved = store.get_task(task.task_id)
        assert retrieved.state == TaskState.RUNNING

    def test_task_state_transitions_are_valid(self, temp_db):
        """Task state transitions follow valid paths."""
        from jaeger_ai.core.tasks.models import DurableTask, TaskKind, TaskState
        from jaeger_ai.core.tasks.store import SqliteDurableTaskStore

        store = SqliteDurableTaskStore(temp_db)

        task = DurableTask(
            task_id="test:transitions",
            owning_agent="test-agent",
            goal="Test transitions",
        )

        # Valid transitions
        valid_transitions = [
            (TaskState.QUEUED, TaskState.RUNNING),
            (TaskState.RUNNING, TaskState.COMPLETED),
            (TaskState.RUNNING, TaskState.FAILED),
            (TaskState.RUNNING, TaskState.CANCELLED),
            (TaskState.QUEUED, TaskState.CANCELLED),
            (TaskState.RUNNING, TaskState.NEEDS_OWNER),
            (TaskState.NEEDS_OWNER, TaskState.RUNNING),
        ]

        for from_state, to_state in valid_transitions:
            task.state = from_state
            store.save_task(task)
            task.state = to_state
            store.save_task(task)
            retrieved = store.get_task(task.task_id)
            assert retrieved.state == to_state


class TestSchedulerProperties:
    """Property-based tests for unified scheduler."""

    @pytest.fixture
    def scheduler(self, tmp_path):
        """Create a unified scheduler with temp database."""
        from jaeger_ai.core.tasks.unified import UnifiedScheduler
        db_path = tmp_path / "scheduler.db"
        return UnifiedScheduler(db_path=db_path, enable_legacy_cron=False)

    def test_card_lifecycle(self, scheduler):
        """Cards can be created, moved, and deleted."""
        # Create
        card = scheduler.add_card("Test task", column="backlog")
        assert card.column == "backlog"
        assert scheduler.get_card(card.card_id) is not None

        # Move
        moved = scheduler.move_card(card.card_id, "in_progress")
        assert moved.column == "in_progress"

        # List
        cards = scheduler.list_cards(column="in_progress")
        assert len(cards) == 1
        assert cards[0].card_id == card.card_id

        # Delete
        assert scheduler.remove_card(card.card_id) is True
        assert scheduler.get_card(card.card_id) is None

    def test_board_summary_consistency(self, scheduler):
        """Board summary counts match actual cards."""
        # Add cards to different columns
        scheduler.add_card("Task 1", column="backlog")
        scheduler.add_card("Task 2", column="backlog")
        scheduler.add_card("Task 3", column="in_progress")
        scheduler.add_card("Task 4", column="done")

        summary = scheduler.board_summary()
        assert summary["backlog"] == 2
        assert summary["in_progress"] == 1
        assert summary["done"] == 1
        assert summary["ready"] == 0
        assert summary["blocked"] == 0

        # Total should match card count
        total_cards = len(scheduler.list_cards())
        total_summary = sum(summary.values())
        assert total_cards == total_summary

    def test_invalid_column_rejected(self, scheduler):
        """Invalid column names are rejected."""
        with pytest.raises(ValueError):
            scheduler.add_card("Test", column="invalid_column")

        card = scheduler.add_card("Test", column="backlog")
        with pytest.raises(ValueError):
            scheduler.move_card(card.card_id, "invalid_column")


class TestTaskKindProperties:
    """Test TaskKind enum properties."""

    def test_all_kinds_have_values(self):
        """All task kinds have string values."""
        from jaeger_ai.core.tasks.models import TaskKind

        for kind in TaskKind:
            assert isinstance(kind.value, str)
            assert len(kind.value) > 0

    def test_scheduled_job_kind(self):
        """Scheduled jobs use the correct kind."""
        from jaeger_ai.core.tasks.models import TaskKind

        assert TaskKind.SCHEDULED_JOB.value == "scheduled_job"


class TestTaskStateProperties:
    """Test TaskState enum properties."""

    def test_terminal_states(self):
        """Terminal states are correctly identified."""
        from jaeger_ai.core.tasks.models import DurableTask, TaskState

        terminal_states = [
            TaskState.COMPLETED,
            TaskState.COMPLETED_VERIFIED,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.NEEDS_OWNER,
            TaskState.BLOCKED,
        ]

        for state in terminal_states:
            task = DurableTask(
                task_id="test",
                owning_agent="test",
                goal="test",
                state=state,
            )
            assert task.is_terminal, f"{state} should be terminal"

    def test_non_terminal_states(self):
        """Non-terminal states are correctly identified."""
        from jaeger_ai.core.tasks.models import DurableTask, TaskState

        non_terminal_states = [
            TaskState.QUEUED,
            TaskState.RUNNING,
            TaskState.PAUSED,
        ]

        for state in non_terminal_states:
            task = DurableTask(
                task_id="test",
                owning_agent="test",
                goal="test",
                state=state,
            )
            assert not task.is_terminal, f"{state} should not be terminal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
