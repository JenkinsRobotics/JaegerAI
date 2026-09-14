"""Cross-test isolation for process-wide Jaeger Agent state."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("JAEGER_NO_GUI", "1")
os.environ.setdefault("JAEGER_NO_ATTACH", "1")


@pytest.fixture(autouse=True)
def _agent_state_outside_the_repo(tmp_path):
    """Run this suite from a temp directory, not the checkout.

    ``DefaultWorkspace`` roots at ``<cwd>/.jaeger_agent`` deliberately — "a
    robot's workspace lives with the robot's code" — so the default is right
    and is not what changes here. What was wrong is the CWD: tests that build
    an agent without passing ``root=`` inherited the repository root, and the
    suite wrote logs, memory, skills and a workspace straight into the
    checkout. That is the in-repo runtime state ``AGENTS.md`` forbids, and
    ``test_repo_root_has_zero_runtime_junk`` fails on it.

    It went unseen because this suite was not in ``testpaths``: nothing ran it
    by default, so nothing checked the tree afterwards.

    Per-test, not per-session: a session-scoped version does not restore the
    directory until the whole run ends, so the application suite executing
    afterwards inherited this temp CWD and failed.
    """
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield
    finally:
        os.chdir(previous)


_PREVIOUS_STATE = os.environ.get("JAEGER_STATE_DIR")
_TEST_STATE = tempfile.mkdtemp(prefix="jaeger-agent-tests-", dir="/tmp")
os.environ["JAEGER_STATE_DIR"] = _TEST_STATE


def pytest_unconfigure(config):
    if _PREVIOUS_STATE is None:
        os.environ.pop("JAEGER_STATE_DIR", None)
    else:
        os.environ["JAEGER_STATE_DIR"] = _PREVIOUS_STATE
    shutil.rmtree(_TEST_STATE, ignore_errors=True)


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


def _register_tool_surface() -> None:
    """Restore the captured built-in surface without reloading module state."""
    from jaeger_os.core.tools.tool_registry import restore_registry
    if _registry_snapshot is not None:
        restore_registry(_registry_snapshot)


@pytest.fixture()
def live_tools():
    _register_tool_surface()
    from jaeger_os.core.tools.tool_registry import get_tools
    return {tool.name: tool for tool in get_tools()}
