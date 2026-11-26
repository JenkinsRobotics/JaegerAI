"""Hygiene & smoke tests for new-user CLI (`./jaeger`), installer (`./install.sh`), and `pyproject.toml`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_cli_help_and_entrypoint_work() -> None:
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "jaeger_ai", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )
    assert proc.returncode == 0
    assert "JaegerAI Operator CLI" in proc.stdout
    assert "./jaeger start" in proc.stdout


def test_setup_dry_run_and_pyproject_workspace_sync() -> None:
    proc = subprocess.run(
        ["bash", str(REPO / "scripts/setup.sh"), "--profile", "full", "--dry-run"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )
    assert proc.returncode == 0
    assert "jaeger-droid" in proc.stdout

    pyproj = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert '"packages/jaeger-ui-avatar"' in pyproj
    assert "jaeger-droid = { workspace = true }" in pyproj
    assert "jaeger-cognition = { workspace = true }" in pyproj
