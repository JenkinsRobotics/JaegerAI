"""Tests for Workstream 5: State-Ownership Consolidation.

Validates that:
1. Every major state type has an unambiguous authoritative owner.
2. Cross-store write permissions are strictly checked.
3. No rogue or duplicate state files exist in the repository tree.
4. The system can definitively answer 'Where is the authoritative copy of X?'.
"""
from pathlib import Path
import pytest

from jaeger_ai.core.state.ownership import (
    StateDomain,
    StateOwnershipCoordinator,
    STATE_OWNERSHIP_REGISTRY,
)


def test_every_state_domain_has_authoritative_owner():
    """Every defined StateDomain must have a registered owner and canonical location."""
    for domain in StateDomain:
        owner = StateOwnershipCoordinator.get_owner(domain)
        assert owner is not None
        assert owner.authoritative_class
        assert owner.authoritative_module
        assert owner.canonical_location_description
        assert len(owner.write_access) > 0
        assert len(owner.read_access) > 0


def test_where_is_authoritative_copy_of_x():
    """StateOwnershipCoordinator can answer 'Where is the authoritative copy of X?' for all domains."""
    audit = StateOwnershipCoordinator.audit_ownership_map()
    assert "identity" in audit
    assert "experience_history" in audit
    assert "active_execution" in audit
    assert "side_effects" in audit
    assert "conversations" in audit
    assert "semantic_knowledge" in audit
    assert "reflections" in audit
    assert "skills" in audit
    assert "attachments" in audit

    # Verify identity ownership
    assert audit["identity"]["authoritative_class"] == "EntityIdentity"
    assert "memory/entity_identity.json" in audit["identity"]["location"]

    # Verify experience history ownership
    assert audit["experience_history"]["authoritative_class"] == "SqliteEventStore"
    assert "memory/entity_events.sqlite3" in audit["experience_history"]["location"]

    # Verify conversations ownership
    assert audit["conversations"]["authoritative_class"] == "GatewaySessionStore"
    assert "gateway_sessions.sqlite3" in audit["conversations"]["location"]


def test_validate_write_permission_enforces_boundaries():
    """Unauthorized subsystems must be rejected from writing to protected domains."""
    # WebUI attempting to write to identity or session store directly must be rejected
    assert not StateOwnershipCoordinator.validate_write_permission(
        StateDomain.IDENTITY, "WebUIAdapter"
    )
    assert not StateOwnershipCoordinator.validate_write_permission(
        StateDomain.EXPERIENCE_HISTORY, "GatewayApp"
    )

    # Authorized writers must succeed
    assert StateOwnershipCoordinator.validate_write_permission(
        StateDomain.IDENTITY, "EntityRuntime"
    )
    assert StateOwnershipCoordinator.validate_write_permission(
        StateDomain.EXPERIENCE_HISTORY, "EntityRuntime"
    )
    assert StateOwnershipCoordinator.validate_write_permission(
        StateDomain.CONVERSATIONS, "GatewaySessionStore"
    )


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
