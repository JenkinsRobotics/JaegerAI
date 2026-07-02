"""Pytest configuration for the Jaeger-OS framework test suite.

Kept deliberately small — the framework tests are self-contained and do
not need fixtures. ``QT_QPA_PLATFORM`` is defaulted to ``offscreen`` so
any interface test that imports a GUI toolkit does not hard-abort on a
headless runner before pytest can report a normal result.

Auto-markers: rather than hand-annotating ~80 test files, this
conftest infers a marker tier from each test's path. The convention:

  * tests/jaeger_os/daemon/ ........... subprocess + slow (real forks)
  * tests/jaeger_os/interfaces/tui/ ... ui (TUI rendering / rumps)
  * tests/jaeger_os/interfaces/pyside6/tray/ .. ui (menu-bar tray)
  * tests/jaeger_os/skills/test_computer_use* .. ui (Apple Events)
  * tests/jaeger_os/skills/test_macos_background* .. subprocess
  * tests/jaeger_os/agent/test_context_guard_integration .. integration
  * everything else ................... unmarked (fast unit)

Plus an explicit ``smoke`` list — the curated 30-ish probes that
exercise the most surface in the least time. ``pytest -m smoke``
should turn green in under 5s on a fresh checkout. Tests still
in the smoke list keep ``smoke`` AND any path-inferred marker.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Path-based marker rules. Order matters — first match wins.
_PATH_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("/jaeger_os/daemon/test_lifecycle_e2e",  ("subprocess", "slow")),
    ("/jaeger_os/daemon/test_protocol",       ("subprocess",)),
    ("/jaeger_os/daemon/test_lifecycle",      ("subprocess",)),
    ("/jaeger_os/interfaces/tui/",            ("ui",)),
    ("/jaeger_os/interfaces/pyside6/tray/",           ("ui",)),
    ("/jaeger_os/skills/test_computer_use",   ("ui",)),
    ("/jaeger_os/skills/test_macos_background", ("subprocess",)),
    ("/jaeger_os/agent/test_context_guard_integration", ("integration",)),
    ("/jaeger_os/agent/test_runtime_bridge",  ("integration",)),
    ("/jaeger_os/agent/test_liveness",        ("integration",)),
    ("/jaeger_os/agent/test_run_turn",        ("integration",)),
]


# Smoke list — the curated cheap probes. Matched as a SUBSTRING of the
# test's nodeid so a file like ``test_diagnostics.py`` adds all 8 of
# its tests to smoke in one entry.
_SMOKE_FILES: tuple[str, ...] = (
    "test_diagnostics.py",
    "test_process_slot.py",
    "test_prompt_assembly.py",
    "test_context_guard.py",   # not the integration variant — that path is excluded
    "test_drift_parser.py",
    "test_bench.py",
    "test_board_autonomy.py",
    "test_preflight.py",
    "test_session_commands.py",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply path-derived markers + the smoke tag to every collected
    item. Idempotent — running twice yields the same marker set."""
    for item in items:
        # Pytest's nodeid looks like
        # ``tests/jaeger_os/.../test_foo.py::test_bar``. Use the
        # path part (Path() handles both forward and back slashes).
        rel = "/" + str(Path(item.fspath)).replace("\\", "/").split("tests/", 1)[-1]
        for prefix, markers in _PATH_MARKERS:
            if prefix in rel:
                for m in markers:
                    item.add_marker(getattr(pytest.mark, m))
                break
        if any(s in rel for s in _SMOKE_FILES) \
           and "test_context_guard_integration" not in rel:
            item.add_marker(pytest.mark.smoke)


# Reset the live agent-status indicator before every test so state set
# in one test (e.g. the agent_status / TUI tests) doesn't leak into
# tests that assume a clean idle state. Tiny dict write; doesn't affect
# any test that doesn't read or write ``_pipeline["agent_status"]``.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _reset_agent_status() -> None:
    """Reset the global live-activity snapshot to ``ready`` before each
    test. Prevents the previous test's status from bleeding into the
    next — important because ``set_agent_status`` is a process-global
    write, not a per-instance one."""
    try:
        from jaeger_os.main import set_agent_status
    except Exception:  # noqa: BLE001 — agent_status is optional during partial migrations
        return
    set_agent_status("ready", "")


@_pytest.fixture(scope="session")
def _full_tool_registry_snapshot():
    """The COMPLETE tool registry, captured once: module-registered tools
    (registered as an import side-effect in tools/*.py, which CANNOT be
    re-run after a clear_registry() because the modules are import-cached)
    PLUS the remaining main.py builtins."""
    import jaeger_os.agent.tools  # noqa: F401 — module-level tool registrations
    from jaeger_os.agent.schemas import tool_registry as R
    try:
        from jaeger_os.main import _register_builtins
        _register_builtins(None)   # register-only; client is unused at def time
    except Exception:  # noqa: BLE001
        pass
    return dict(R._registry)


@_pytest.fixture(autouse=True)
def _restore_tool_registry(_full_tool_registry_snapshot):
    """Restore the full tool registry after every test. Post
    tool-standardization, most tools register on module import; a test that
    calls clear_registry() would otherwise strand those module tools for the
    whole rest of the session (imports are cached, so they can't re-fire)."""
    from jaeger_os.agent.schemas import tool_registry as R
    yield
    R._registry.clear()
    R._registry.update(_full_tool_registry_snapshot)
