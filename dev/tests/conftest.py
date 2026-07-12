"""Pytest configuration for the JaegerOS framework test suite.

Kept deliberately small — the framework tests are self-contained and do
not need fixtures.

Pruned during the 0.9 four-way split (dev/docs/roadmap/SPLIT_FILE_MAP.md
in the JROS repo): the monorepo's conftest.py carried three fixtures
(``_reset_agent_status``, ``_full_tool_registry_snapshot``,
``_restore_tool_registry``) that hard-import ``jaeger_os.agent`` /
``jaeger_os.main`` — Mind-owned modules that do not exist in this repo.
Removed rather than guarded: they exist to manage agent-loop state
across tests, which is meaningless for a suite that never boots a Mind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Path-based marker rules. Order matters — first match wins.
_PATH_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("/jaeger_os/hardware/", ("integration",)),
]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply path-derived markers to every collected item. Idempotent —
    running twice yields the same marker set."""
    for item in items:
        rel = "/" + str(Path(item.fspath)).replace("\\", "/").split("tests/", 1)[-1]
        for prefix, markers in _PATH_MARKERS:
            if prefix in rel:
                for m in markers:
                    item.add_marker(getattr(pytest.mark, m))
                break
