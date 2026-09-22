"""
ARES SI — Core type definitions.

All type definitions that other SI subsystems depend on.
No implementation logic — only data classes and protocols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


# ── Data Classifications ──────────────────────────────────────────────

class DataClassification(str, Enum):
    """Sensitivity levels for Journal data and context items."""
    PUBLIC = "public"        # General knowledge, public docs
    PERSONAL = "personal"    # User preferences, project names, habits
    PRIVATE = "private"      # Personal conversations, health, relationships
    SENSITIVE = "sensitive"  # Financial, medical, legal data
    SECRET = "secret"        # API keys, passwords, auth tokens


PUBLIC = DataClassification.PUBLIC
PERSONAL = DataClassification.PERSONAL
PRIVATE = DataClassification.PRIVATE
SENSITIVE = DataClassification.SENSITIVE
SECRET = DataClassification.SECRET


class PrivacyClass(str, Enum):
    """Who a worker is allowed to see data from."""
    LOCAL_ONLY = "local_only"              # Only local workers (Ollama, local Jaeger)
    APPROVED_PROVIDER = "approved_provider" # Cloud providers the user has approved
    EXTERNAL_PROVIDER = "external_provider" # Any cloud provider
    UNRESTRICTED = "unrestricted"           # No restrictions (public data)


# ── SI Identity ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class SIIdentity:
    """Who the SI is — injected into every briefing."""
    name: str                              # What the SI calls itself
    owner_name: str                        # What the SI calls the user
    mission: str = ""                      # Core mission statement
    principles: list[str] = field(default_factory=list)  # Behavioral principles
    loyalty: str = "user"                  # Always "user" — the SI works for the owner


# ── Context Types ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContextItem:
    """A single piece of context included in a briefing."""
    source: str                # "conversation", "document", "preference", "decision"
    source_id: str             # ID in the Journal
    content: str               # The actual text
    sensitivity: DataClassification = PERSONAL
    relevance: float = 0.5    # 0.0–1.0 how relevant to the current task
    recency: float = 1.0      # 0.0–1.0 how recent (1.0 = just now)
    is_decision: bool = False  # True if this was a final decision, not exploration


@dataclass(frozen=True)
class MemoryItem:
    """A memory retrieved from the Journal for a briefing."""
    memory_id: str
    content: str
    source: str               # "conversation", "document", "preference"
    sensitivity: DataClassification = PERSONAL
    importance: float = 0.5   # 0.0–1.0
    created_at: float = 0.0


@dataclass(frozen=True)
class Constraint:
    """A constraint on what the worker should or should not do."""
    kind: str                  # "must", "must_not", "prefer", "avoid"
    description: str
    reason: str = ""           # Why this constraint exists


@dataclass(frozen=True)
class OutputSpec:
    """What the SI expects back from the worker."""
    format: str = "text"       # "text", "code", "json", "markdown"
    max_length: int | None = None
    style: str = ""            # "concise", "detailed", "technical", "casual"
    language: str = ""         # Programming language for code tasks


class ManifestAction(str, Enum):
    """What happened to a context item during compilation."""
    INCLUDED = "included"
    EXCLUDED = "excluded"
    REDACTED = "redacted"
    SUMMARIZED = "summarized"


@dataclass(frozen=True)
class ManifestEntry:
    """Explains what was included/excluded/redacted in a briefing."""
    item_id: str
    action: ManifestAction
    reason: str              # "relevant", "over_budget", "privacy:private_to_cloud", etc.
    original_tokens: int = 0
    final_tokens: int = 0


@dataclass
class ContextBriefing:
    """The filtered, budgeted context that the SI sends to a worker.

    This is the ONLY data structure that crosses the SI→Worker boundary.
    Workers never see the full Journal — only the briefing.
    """
    si_identity: SIIdentity
    user_context: list[ContextItem] = field(default_factory=list)
    project_context: list[ContextItem] = field(default_factory=list)
    recent_conversation: list[ContextItem] = field(default_factory=list)
    relevant_memories: list[MemoryItem] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    privacy_policy: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    output_requirements: OutputSpec = field(default_factory=OutputSpec)
    context_manifest: list[ManifestEntry] = field(default_factory=list)
    total_tokens: int = 0


# ── Worker Result ──────────────────────────────────────────────────────

@dataclass
class WorkerResult:
    """Structured result from a worker.

    Worker outputs are UNTRUSTED INPUT. The evaluator must verify before
    the response composer presents anything to the user.
    """
    worker_id: str
    content: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None      # Worker self-assessed 0.0–1.0
    cost: "CostReport" | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    verification_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CostReport:
    """Cost incurred by a worker for this task."""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    currency: str = "USD"


# ── Worker Types ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkerCapability:
    """A capability that a worker declares."""
    capability_id: str         # "code_generation", "research", "conversation", etc.
    description: str = ""
    proficiency: float = 1.0  # 0.0–1.0 how good at this


@dataclass(frozen=True)
class WorkerRecord:
    """A worker in the registry."""
    worker_id: str             # "claude-code", "ollama-llama3", "jaeger-local"
    provider: str              # "anthropic", "local", "nous"
    display_name: str
    capabilities: list[WorkerCapability] = field(default_factory=list)
    privacy_class: PrivacyClass = PrivacyClass.EXTERNAL_PROVIDER
    data_location: str = "cloud"   # "local" or "cloud"
    context_limit: int | None = None
    supports_streaming: bool = False
    supports_files: bool = False
    supports_images: bool = False
    estimated_cost: CostEstimate | None = None
    latency_profile: LatencyProfile | None = None


@dataclass(frozen=True)
class AvailabilityStatus:
    """Whether a worker is currently available."""
    worker_id: str
    available: bool
    reason: str = ""           # Why unavailable, if applicable
    checked_at: float = 0.0


@dataclass(frozen=True)
class CostEstimate:
    """Estimated cost for a worker."""
    input_cost_per_1k: float   # USD per 1K input tokens
    output_cost_per_1k: float  # USD per 1K output tokens
    flat_cost: float = 0.0     # Per-request cost
    currency: str = "USD"


@dataclass(frozen=True)
class LatencyProfile:
    """Expected latency for a worker."""
    average_response_ms: int = 0
    first_token_ms: int = 0
    p95_response_ms: int = 0


# ── Plan Types ─────────────────────────────────────────────────────────

class PlanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"


@dataclass
class Step:
    """One step in a plan."""
    step_id: str
    objective: str
    dependencies: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    assigned_worker: str | None = None
    status: StepStatus = StepStatus.PENDING
    result: str | None = None
    evaluation: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    requires_approval: bool = False


@dataclass
class Plan:
    """A multi-step plan for a complex task."""
    plan_id: str
    goal: str
    status: PlanStatus = PlanStatus.PENDING
    steps: list[Step] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    conversation_id: str | None = None