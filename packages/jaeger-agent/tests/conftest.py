"""Cross-test isolation for process-wide Jaeger Agent state."""

from __future__ import annotations

import pytest


_registry_snapshot: dict | None = None


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001
    """Capture the complete built-in registry before any test can clear it.

    Tool modules register through import side effects.  Re-importing the
    already-cached ``jaeger_agent.tools`` package cannot recreate entries
    removed by a test, so a durable snapshot is the only order-independent
    reset mechanism.
    """
    global _registry_snapshot

    import jaeger_agent.tools  # noqa: F401 -- populate built-in tools
    from jaeger_os.core.tools.tool_registry import snapshot_registry

    _registry_snapshot = snapshot_registry()


@pytest.fixture(autouse=True)
def _restore_tool_registry() -> None:
    """Restore built-ins around every test that mutates the registry."""
    from jaeger_os.core.tools.tool_registry import restore_registry

    if _registry_snapshot is not None:
        restore_registry(_registry_snapshot)
    yield
    if _registry_snapshot is not None:
        restore_registry(_registry_snapshot)
