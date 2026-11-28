"""Repository hygiene guard: zero in-repo runtime state, virtualenvs, or legacy shims."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_ROOT_NAMES = {
    ".venv",
    ".jaeger_ai",
    ".jaeger_agent",
    ".jaeger_os",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "jaeger_ai.egg-info",
}


def test_repo_root_has_zero_runtime_junk() -> None:
    found = [p.name for p in REPO_ROOT.iterdir() if p.name in FORBIDDEN_ROOT_NAMES]
    assert not found, f"Forbidden runtime directories in repo root: {found}"


def test_no_in_repo_ui_dist() -> None:
    assert not (REPO_ROOT / "jaeger_ai/interfaces/ui/dist").exists()
