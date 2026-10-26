"""Conftest for unit tests — fast, no external dependencies."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "jaeger-agent"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "jaeger-os"))


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch):
    """Reset environment variables before each test."""
    # Set test mode
    monkeypatch.setenv("JAEGER_TEST_MODE", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    yield
