"""Repo-root pytest hooks.

Applies to every test collected from this tree, including
``packages/jaeger-agent/tests`` when it is invoked alongside ``dev/tests``.
The tool registry is process-global and tools register on import; a case
that calls ``clear_registry()`` would otherwise empty the map for every
later case, because cached imports cannot re-fire their decorators.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
# AGENTS.md §1: bytecode never lands in the source tree, even when this
# conftest is imported before PYTHONDONTWRITEBYTECODE/PYTHONPYCACHEPREFIX
# could take effect (e.g. a bare `pytest` from the repo root with a
# Homebrew python that ignores -B). Redirect the cache out of the repo so
# the root __pycache__ tripwire cannot fire. The pyc for THIS file is the
# one exception: python must write it to cache or package-compile it
# before running conftest, and PYTHONPYCACHEPREFIX (set by verify.sh and
# ci-local.sh) already covers that case; the setdefault keeps a direct
# invocation safe too.
os.environ.setdefault("PYTHONPYCACHEPREFIX", os.path.expanduser("~/.cache/jaeger/pycache"))
os.environ.setdefault("JAEGER_NO_GUI", "1")
os.environ.setdefault("JAEGER_NO_ATTACH", "1")

import pytest

from jaeger_os.core.tools.tool_registry import restore_registry, snapshot_registry

_REGISTRY_SNAPSHOT: dict | None = None


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001
    global _REGISTRY_SNAPSHOT
    import jaeger_agent.tools  # noqa: F401
    try:
        from jaeger_ai.main import _register_builtins
        _register_builtins(None)
    except Exception:  # noqa: BLE001
        pass
    _REGISTRY_SNAPSHOT = snapshot_registry()


@pytest.fixture(autouse=True)
def _restore_tool_registry_root():
    if _REGISTRY_SNAPSHOT is not None:
        restore_registry(_REGISTRY_SNAPSHOT)
    yield
    if _REGISTRY_SNAPSHOT is not None:
        restore_registry(_REGISTRY_SNAPSHOT)
