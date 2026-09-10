"""CI Hygiene and Clean Repository Guard.

Guarantees that JaegerAI adheres strictly to the OpenClaw standard:
  1. Zero in-repo runtime state, virtualenvs, or caches.
  2. No code writes databases, state, or instances into the git working tree.
  3. All persistent state routes cleanly to ~/.jaeger/.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

FORBIDDEN_ROOT_NAMES = {
    ".venv",
    ".jaeger_ai",
    ".jaeger_agent",
    ".jaeger_os",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode",
    "jaeger_ai.egg-info",
}


def test_repo_root_has_zero_runtime_junk():
    """Ensure no runtime artifacts or local virtualenvs pollute the git root."""
    found_forbidden = [
        p.name for p in REPO_ROOT.iterdir()
        if p.name in FORBIDDEN_ROOT_NAMES
    ]
    assert not found_forbidden, (
        f"Forbidden runtime junk directories found in repo root: {found_forbidden}. "
        "All state belongs in ~/.jaeger and all virtualenvs belong in ~/.jaeger/venv."
    )


def test_no_in_repo_state_writes_in_core():
    """Ensure no source files reintroduce hardcoded state writes to REPO_ROOT."""
    violations: list[str] = []
    source_root = REPO_ROOT / "jaeger_ai"

    for py_file in source_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if 'REPO_ROOT / ".jaeger_ai"' in text or 'REPO_ROOT / ".jaeger_agent"' in text:
            violations.append(str(py_file.relative_to(REPO_ROOT)))

    assert not violations, (
        "Found hardcoded in-repo state writes in the following files:\n"
        + "\n".join(violations)
        + "\nAll runtime state must use operator_state_root() (~/.jaeger)."
    )


def test_operator_state_root_defaults_to_user_home(monkeypatch):
    """Verify that operator_state_root resolves to ~/.jaeger when no test sandbox is set."""
    from jaeger_ai.core.instance.instance import operator_state_root

    monkeypatch.delenv("JAEGER_HOME", raising=False)
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)

    expected = Path.home() / ".jaeger"
    assert operator_state_root() == expected
