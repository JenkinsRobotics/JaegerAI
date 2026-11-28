"""Root pytest configuration for the 100% standalone modular JaegerAI framework."""

from __future__ import annotations

import pytest
from jaeger_tools.tool_registry import restore_registry, snapshot_registry


@pytest.fixture(autouse=True)
def _isolate_tool_registry():
    snap = snapshot_registry()
    yield
    restore_registry(snap)
