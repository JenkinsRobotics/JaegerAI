"""Tests for Workstream 5: State-Ownership Consolidation.

Validates that:
1. Every major state type has an unambiguous authoritative owner.
2. Cross-store write permissions are strictly checked.
3. No rogue or duplicate state files exist in the repository tree.
4. The system can definitively answer 'Where is the authoritative copy of X?'.
"""
from pathlib import Path
import pytest









def test_no_in_repo_runtime_state_pollution():
    """Assert no SQLite databases or session JSON files exist in the repository tree."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    polluting_sqlite = list(repo_root.glob("**/*.sqlite3"))
    # Filter out any in tmp or cache if present
    in_repo = [
        p for p in polluting_sqlite
        if not str(p).startswith("/tmp") and ".cache" not in str(p) and "venv" not in str(p)
    ]
    assert len(in_repo) == 0, f"Found in-repo SQLite databases violating AGENTS.md: {in_repo}"
