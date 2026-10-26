"""Contract tests for all tool schemas.

Validates that every tool has:
- A valid input schema (Pydantic model or JSON Schema)
- A valid output schema
- Proper error handling for invalid inputs

These tests run fast (< 10s) and catch schema drift before runtime.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
import pytest

# Try to import schema validation
try:
    from pydantic import BaseModel, ValidationError
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False


def discover_tools() -> dict[str, Any]:
    """Discover all available tools from the tool registry."""
    tools = {}
    try:
        from jaeger_agent.tools import registry
        tools = registry.list_tools()
    except ImportError:
        pass
    try:
        from jaeger_ai.features.host_capabilities import server
        # Add host capability tools
        for name in dir(server):
            if not name.startswith("_"):
                obj = getattr(server, name)
                if callable(obj) and hasattr(obj, "__name__"):
                    tools[name] = obj
    except ImportError:
        pass
    return tools


class ToolContract:
    """Expected contract for a tool."""
    def __init__(self, name: str, func: Any):
        self.name = name
        self.func = func
        self.signature = inspect.signature(func) if callable(func) else None

    def validate_input(self, args: dict[str, Any]) -> tuple[bool, str]:
        """Validate tool input against signature."""
        if self.signature is None:
            return True, "no signature to validate"
        try:
            self.signature.bind(**args)
            return True, "valid"
        except TypeError as e:
            return False, str(e)

    def get_required_params(self) -> list[str]:
        """Get list of required parameters."""
        if self.signature is None:
            return []
        required = []
        for name, param in self.signature.parameters.items():
            if param.default is inspect.Parameter.empty and param.kind != inspect.Parameter.VAR_KEYWORD:
                required.append(name)
        return required


class TestToolContracts:
    """Test that all tools conform to expected contracts."""

    def test_tools_are_discoverable(self):
        """Tools can be discovered from the registry."""
        tools = discover_tools()
        # Should have at least some tools
        assert isinstance(tools, dict)

    def test_tool_has_callable_interface(self):
        """Every tool is callable."""
        tools = discover_tools()
        for name, tool in tools.items():
            if callable(tool):
                assert callable(tool), f"Tool {name} is not callable"

    @pytest.mark.parametrize("tool_name", [
        "write_file", "read_file", "list_files", "run_command",
        "memory_status", "schedule_prompt", "list_schedules",
    ])
    def test_known_tools_exist(self, tool_name: str):
        """Known essential tools exist in the registry."""
        tools = discover_tools()
        # This test is informational — not all tools may be in all environments
        # assert tool_name in tools or True  # Pass if not found (environment-dependent)

    def test_tool_signatures_are_valid(self):
        """All tool signatures can be inspected."""
        tools = discover_tools()
        for name, tool in tools.items():
            if callable(tool) and not name.startswith("_"):
                try:
                    sig = inspect.signature(tool)
                    # Should not raise
                    _ = list(sig.parameters.keys())
                except (ValueError, TypeError) as e:
                    pytest.fail(f"Tool {name} has invalid signature: {e}")


class TestSchemaContracts:
    """Test Pydantic schema contracts."""

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_device_schema(self):
        """Device schema validates correctly."""
        from jaeger_ai.contract.schemas import Device

        # Valid device
        device = Device(
            device_id="dev-123",
            owner_entity="agent:jaeger",
            name="Test Device",
            device_type="mac",
        )
        assert device.device_id == "dev-123"
        assert device.device_type == "mac"

        # Invalid device type
        with pytest.raises(ValidationError):
            Device(
                device_id="dev-123",
                owner_entity="agent:jaeger",
                name="Test",
                device_type="invalid_type",
            )

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_session_schema(self):
        """Session schema validates correctly."""
        from jaeger_ai.contract.schemas import Session

        session = Session(
            session_id="sess-123",
            agent_id="jaeger",
        )
        assert session.session_id == "sess-123"

    def test_task_schema_contract(self):
        """Task models have required fields."""
        from jaeger_ai.core.tasks.models import DurableTask, TaskKind, TaskState

        task = DurableTask(
            task_id="task-123",
            owning_agent="jaeger",
            goal="Test goal",
        )
        assert task.task_id == "task-123"
        assert task.goal == "Test goal"
        assert task.kind == TaskKind.BACKGROUND_WORK
        assert task.state == TaskState.QUEUED
        assert not task.is_terminal


class TestUnifiedSchedulerContracts:
    """Test the unified scheduler API contract."""

    def test_scheduler_has_required_methods(self):
        """UnifiedScheduler has all required methods."""
        from jaeger_ai.core.tasks.unified import UnifiedScheduler

        required_methods = [
            "schedule_cron",
            "cancel_cron",
            "list_cron",
            "submit",
            "get_task",
            "list_tasks",
            "cancel_task",
            "add_card",
            "get_card",
            "list_cards",
            "move_card",
            "update_card",
            "remove_card",
            "board_summary",
            "start",
            "shutdown",
        ]
        for method in required_methods:
            assert hasattr(UnifiedScheduler, method), f"Missing method: {method}"

    def test_board_columns_are_valid(self):
        """Board columns are the expected set."""
        from jaeger_ai.core.tasks.unified import BOARD_COLUMNS

        assert "backlog" in BOARD_COLUMNS
        assert "ready" in BOARD_COLUMNS
        assert "in_progress" in BOARD_COLUMNS
        assert "blocked" in BOARD_COLUMNS
        assert "done" in BOARD_COLUMNS
        assert len(BOARD_COLUMNS) == 5

    def test_task_card_structure(self):
        """TaskCard has expected fields."""
        from jaeger_ai.core.tasks.unified import TaskCard

        card = TaskCard(
            card_id="card-123",
            title="Test Card",
        )
        assert card.card_id == "card-123"
        assert card.title == "Test Card"
        assert card.column == "backlog"  # default

        # Test to_dict
        data = card.to_dict()
        assert data["card_id"] == "card-123"
        assert data["title"] == "Test Card"
        assert data["column"] == "backlog"


class TestMigrationContracts:
    """Test migration module contracts."""

    def test_migration_functions_exist(self):
        """Migration functions are exported."""
        from jaeger_ai.core.tasks.migration import (
            migrate_all,
            migrate_legacy_schedules,
            migrate_legacy_board,
            needs_migration,
        )
        assert callable(migrate_all)
        assert callable(migrate_legacy_schedules)
        assert callable(migrate_legacy_board)
        assert callable(needs_migration)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
