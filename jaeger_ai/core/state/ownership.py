"""State Ownership Architecture and Invariant Enforcement (Workstream 5).

Single Source of Truth Doctrine:
- Every persistent state domain in JaegerAI has EXACTLY ONE authoritative owner.
- Other subsystems may project, cache, or index, but never mutate authoritative storage directly.
- Subsystem boundaries are strictly enforced:
    - WebUI never directly writes to Gateway SQLite.
    - Gateway never directly writes to Entity Experience or Claims databases.
    - JaegerAgent never writes to Gateway Session storage.
    - Entity Identity is immutable across model swaps and restarts.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class StateDomain(str, Enum):
    IDENTITY = "identity"
    EXPERIENCE_HISTORY = "experience_history"
    CURRENT_SELF_STATE = "current_self_state"
    ACTIVE_EXECUTION = "active_execution"
    SIDE_EFFECTS = "side_effects"
    CONVERSATIONS = "conversations"
    SEMANTIC_KNOWLEDGE = "semantic_knowledge"
    REFLECTIONS = "reflections"
    SKILLS = "skills"
    ATTACHMENTS = "attachments"
    PROVIDER_CERTIFICATIONS = "provider_certifications"


@dataclass(frozen=True)
class StateOwner:
    """Descriptor for an authoritative owner of a state domain."""

    domain: StateDomain
    authoritative_class: str
    authoritative_module: str
    canonical_location_description: str
    read_access: tuple[str, ...]
    write_access: tuple[str, ...]
    is_projected: bool = False
    projection_source: StateDomain | None = None


# Formal Registry of State Ownership
STATE_OWNERSHIP_REGISTRY: Mapping[StateDomain, StateOwner] = {
    StateDomain.IDENTITY: StateOwner(
        domain=StateDomain.IDENTITY,
        authoritative_class="EntityIdentity",
        authoritative_module="jaeger_ai.core.entity.identity",
        canonical_location_description="<instance>/memory/entity_identity.json",
        read_access=("*",),
        write_access=("EntityRuntime", "first_boot_wizard"),
    ),
    StateDomain.EXPERIENCE_HISTORY: StateOwner(
        domain=StateDomain.EXPERIENCE_HISTORY,
        authoritative_class="SqliteEventStore",
        authoritative_module="jaeger_ai.core.entity.event_store",
        canonical_location_description="<instance>/memory/entity_events.sqlite3",
        read_access=("EntityRuntime", "IndexCoordinator", "LearningPipeline"),
        write_access=("EntityRuntime",),
    ),
    StateDomain.CURRENT_SELF_STATE: StateOwner(
        domain=StateDomain.CURRENT_SELF_STATE,
        authoritative_class="SelfState",
        authoritative_module="jaeger_ai.core.entity.self_state",
        canonical_location_description="In-memory deterministic replay projection from entity_events.sqlite3",
        read_access=("EntityRuntime", "ExecutiveStrategySelector", "CognitionRouter"),
        write_access=("SelfState.apply_event",),
        is_projected=True,
        projection_source=StateDomain.EXPERIENCE_HISTORY,
    ),
    StateDomain.ACTIVE_EXECUTION: StateOwner(
        domain=StateDomain.ACTIVE_EXECUTION,
        authoritative_class="SqliteRunStore",
        authoritative_module="jaeger_agent.cognition.sqlite_runs",
        canonical_location_description="<instance>/data/runs.sqlite3",
        read_access=("EntityRuntime", "TurnExecutive", "RunLifecycleCoordinator", "GatewaySessionStore"),
        write_access=("SqliteRunStore", "RunLifecycleCoordinator"),
    ),
    StateDomain.SIDE_EFFECTS: StateOwner(
        domain=StateDomain.SIDE_EFFECTS,
        authoritative_class="SqliteRunStore (EffectLedger)",
        authoritative_module="jaeger_agent.cognition.sqlite_runs",
        canonical_location_description="<instance>/data/runs.sqlite3 [effects table]",
        read_access=("EntityRuntime", "VerificationRegistry", "TurnExecutive"),
        write_access=("SqliteRunStore.claim_effect", "SqliteRunStore.resolve_effect"),
    ),
    StateDomain.CONVERSATIONS: StateOwner(
        domain=StateDomain.CONVERSATIONS,
        authoritative_class="GatewaySessionStore",
        authoritative_module="jaeger_ai.core.gateway.session_store",
        canonical_location_description="~/.jaeger/gateway_sessions.sqlite3",
        read_access=("GatewayApp", "WebUIAdapter", "SwiftBridgeClient", "TUIClient"),
        write_access=("GatewaySessionStore",),
    ),
    StateDomain.SEMANTIC_KNOWLEDGE: StateOwner(
        domain=StateDomain.SEMANTIC_KNOWLEDGE,
        authoritative_class="SemanticMemory (SqliteClaimStore)",
        authoritative_module="jaeger_agent.memory.sqlite_store",
        canonical_location_description="<instance>/data/memory.sqlite3 [claims table]",
        read_access=("EntityRuntime", "TurnExecutive", "DeliberatePlanner"),
        write_access=("SemanticMemory.record_claim",),
    ),
    StateDomain.REFLECTIONS: StateOwner(
        domain=StateDomain.REFLECTIONS,
        authoritative_class="ReflexionStore",
        authoritative_module="jaeger_ai.core.entity.reflexion_store",
        canonical_location_description="<instance>/memory/structured_reflections.json",
        read_access=("EntityRuntime", "CognitionRouter", "DeliberatePlanner"),
        write_access=("ReflexionStore.append",),
    ),
    StateDomain.SKILLS: StateOwner(
        domain=StateDomain.SKILLS,
        authoritative_class="SkillPipeline / SkillRegistry",
        authoritative_module="jaeger_agent.skills.skills_core",
        canonical_location_description="<instance>/skills/",
        read_access=("EntityRuntime", "CognitionRouter", "SkillPipeline"),
        write_access=("SkillPipeline.promote", "operator_cli"),
    ),
    StateDomain.ATTACHMENTS: StateOwner(
        domain=StateDomain.ATTACHMENTS,
        authoritative_class="GatewaySessionStore & WorkspaceFilesystem",
        authoritative_module="jaeger_ai.core.gateway.session_store",
        canonical_location_description="<instance>/workspace/uploads/ & gateway_sessions.sqlite3 [attachments]",
        read_access=("EntityRuntime", "GatewayApp", "MultimodalVisionProcessor"),
        write_access=("GatewayApp.handle_upload",),
    ),
    StateDomain.PROVIDER_CERTIFICATIONS: StateOwner(
        domain=StateDomain.PROVIDER_CERTIFICATIONS,
        authoritative_class="ProviderCertificationRegistry",
        authoritative_module="jaeger_ai.features.webui.adapter.profile_catalog",
        canonical_location_description="Live runtime probe & certifications table",
        read_access=("GatewayApp", "WebUI", "EntityRuntime"),
        write_access=("CertificationHarness",),
    ),
}


class StateOwnershipCoordinator:
    """Enforces state ownership boundaries and validates cross-system operations."""

    @staticmethod
    def get_owner(domain: StateDomain | str) -> StateOwner:
        """Resolve the authoritative owner for a given state domain."""
        dom = StateDomain(domain) if isinstance(domain, str) else domain
        if dom not in STATE_OWNERSHIP_REGISTRY:
            raise KeyError(f"Unknown state domain: {dom}")
        return STATE_OWNERSHIP_REGISTRY[dom]

    @staticmethod
    def validate_write_permission(domain: StateDomain | str, caller_subsystem: str) -> bool:
        """Assert whether a subsystem is authorized to mutate a given state domain."""
        owner = StateOwnershipCoordinator.get_owner(domain)
        if "*" in owner.write_access:
            return True
        for allowed in owner.write_access:
            if allowed.lower() in caller_subsystem.lower():
                return True
        return False

    @staticmethod
    def audit_ownership_map() -> dict[str, Any]:
        """Return a structured machine-readable state ownership map."""
        return {
            domain.value: {
                "authoritative_class": owner.authoritative_class,
                "authoritative_module": owner.authoritative_module,
                "location": owner.canonical_location_description,
                "is_projected": owner.is_projected,
                "projection_source": owner.projection_source.value if owner.projection_source else None,
                "authorized_writers": list(owner.write_access),
                "authorized_readers": list(owner.read_access),
            }
            for domain, owner in STATE_OWNERSHIP_REGISTRY.items()
        }
