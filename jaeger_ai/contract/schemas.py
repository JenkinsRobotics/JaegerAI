"""Canonical typed contracts and versioned schemas for JaegerAI (Workstream 4).

All cross-boundary data transfers (Control-Plane <-> Runtime, IPC, Storage, Wire)
must validate against these versioned contracts to ensure:
- Malformed payloads fail deterministically with clear diagnostics.
- Safe serialization/deserialization across versions.
- Zero silent schema drift.
"""
from __future__ import annotations

from enum import Enum
import time
from typing import Any, Literal
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION: int = 1


class BaseContract(BaseModel):
    """Base model enforcing schema versioning and strict validation."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    schema_version: int = Field(
        default=SCHEMA_VERSION,
        description="Wire and storage contract schema version",
    )


# ── Execution & Control Plane Contracts ──────────────────────────────────────────


class ExecutionMode(str, Enum):
    AGENT = "agent"
    TEXT_ONLY = "text_only"


class RuntimeRequest(BaseContract):
    """Client turn request submitted to the Control Plane / Gateway."""

    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Unique deterministic identifier for the client request",
    )
    session_id: str = Field(
        ...,
        description="Target session/conversation identifier",
    )
    input_text: str = Field(
        ...,
        min_length=1,
        description="User text or command prompt",
    )
    model: str | None = Field(
        default=None,
        description="Explicitly requested model name/id",
    )
    provider: str | None = Field(
        default=None,
        description="Explicitly requested provider name/id",
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.AGENT,
        description="Cognitive execution mode: agent (tool-using) or text_only",
    )
    actionable: bool = Field(
        default=True,
        description="Whether this request is permitted to cause external side-effects",
    )
    role: str = Field(
        default="lead",
        description="Agent role target (e.g. lead, specialist)",
    )
    attachments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured file or image attachments bound to this turn",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional caller context metadata",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp when request was admitted",
    )


class RuntimeResponse(BaseContract):
    """Standardized response returned from EntityRuntime turn execution."""

    request_id: str = Field(
        ...,
        description="Originating request ID",
    )
    turn_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Turn execution identifier",
    )
    status: Literal["completed", "failed", "cancelled", "running", "interrupted"] = Field(
        default="completed",
        description="Terminal or execution status",
    )
    text: str = Field(
        default="",
        description="Assistant output response text",
    )
    model: str | None = Field(
        default=None,
        description="Model that executed cognition",
    )
    backend: str | None = Field(
        default=None,
        description="Backend/provider that served cognition",
    )
    strategy: str | None = Field(
        default=None,
        description="Executive strategy selected (e.g. react_loop, direct_response)",
    )
    tool_activity: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of tool executions performed during turn",
    )
    capabilities: dict[str, bool] = Field(
        default_factory=dict,
        description="Active runtime capabilities during execution",
    )
    error: str | None = Field(
        default=None,
        description="Error message if execution failed",
    )


# ── State & Storage Schemas ──────────────────────────────────────────────────────


class Session(BaseContract):
    """Persistent conversation session entity."""

    session_id: str = Field(
        ...,
        description="Unique session identifier",
    )
    title: str = Field(
        default="New Conversation",
        description="Human-readable title",
    )
    profile: str = Field(
        default="jaeger",
        description="Session profile framework name",
    )
    runtime: str = Field(
        default="jaeger",
        description="Canonical runtime framework",
    )
    surface: str = Field(
        default="webui",
        description="Ingress surface: webui, cli, tui, app, etc.",
    )
    status: Literal["idle", "running", "execution_unknown", "cancelling", "suspended"] = Field(
        default="idle",
        description="Current conversational state",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary session metadata",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Session creation timestamp",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Last activity timestamp",
    )


class Run(BaseContract):
    """Canonical durable unit of autonomous agent execution."""

    run_id: str = Field(
        ...,
        description="Unique run identifier",
    )
    commitment_id: str = Field(
        ...,
        description="Goal commitment identifier owning this run",
    )
    state: Literal[
        "created", "queued", "running", "waiting_for_approval",
        "waiting_for_event", "verifying", "completed", "failed",
        "cancelled", "interrupted", "recoverable"
    ] = Field(
        default="created",
        description="Canonical lifecycle state",
    )
    attempt: int = Field(
        default=1,
        description="Attempt iteration counter",
    )
    owner_pid: int | None = Field(
        default=None,
        description="Process ID actively executing this run",
    )
    wake_key: str | None = Field(
        default=None,
        description="Key that will resume a waiting run (e.g. approval:<id>)",
    )
    provider: str | None = Field(
        default=None,
        description="Cognition provider executing this run",
    )
    request_id: str | None = Field(
        default=None,
        description="Mapped client request ID (1:1 with durable run)",
    )
    parent_run_id: str | None = Field(
        default=None,
        description="Parent run ID if delegated/nested",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Run context parameters and state checkpoints",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Creation timestamp",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Last updated timestamp",
    )


class AgentEvent(BaseContract):
    """Immutable event record in the Event Fabric."""

    event_id: str = Field(
        ...,
        description="Unique event ID (e.g. ev_xxx)",
    )
    event_type: str = Field(
        ...,
        description="Event classification string",
    )
    actor: str = Field(
        ...,
        description="Entity or subsystem actor that emitted the event",
    )
    source: str = Field(
        ...,
        description="Subsystem or transport source",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Event creation timestamp",
    )
    session_id: str = Field(
        default="dispatcher",
        description="Target session ID",
    )
    request_id: str | None = Field(
        default=None,
        description="Associated request ID",
    )
    parent_event_id: str | None = Field(
        default=None,
        description="Parent event in causal provenance chain",
    )
    salience: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Salience score evaluated by Attention / SalienceEngine",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured event payload",
    )


# ── Policy, Authority & Effects ──────────────────────────────────────────────────


class ProposedAction(BaseContract):
    """Proposed tool action submitted to the Authority kernel."""

    proposal_id: str = Field(
        default_factory=lambda: f"prop_{uuid.uuid4().hex[:12]}",
        description="Unique proposal identifier",
    )
    request_id: str = Field(
        ...,
        description="Associated client request ID",
    )
    run_id: str = Field(
        ...,
        description="Associated run ID",
    )
    action_type: str = Field(
        ...,
        description="Category of action (e.g. file_write, shell_exec, http_post)",
    )
    tool_name: str = Field(
        ...,
        description="Tool name being invoked",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool execution arguments",
    )
    target_path: str | None = Field(
        default=None,
        description="Target resource path if applicable",
    )
    tier: Literal["read_only", "write_local", "write_global", "execute"] = Field(
        default="write_local",
        description="Permission tier required",
    )
    rationale: str = Field(
        default="",
        description="Model reasoning for why this action is necessary",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Proposal creation timestamp",
    )


class AuthorityDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"
    REQUIRE_APPROVAL = "require_approval"


class AuthorityDecision(BaseContract):
    """Deterministic policy decision governing a ProposedAction."""

    decision_id: str = Field(
        default_factory=lambda: f"auth_{uuid.uuid4().hex[:12]}",
        description="Unique decision identifier",
    )
    proposal_id: str = Field(
        ...,
        description="Target proposal identifier",
    )
    decision: AuthorityDecisionType = Field(
        ...,
        description="Policy outcome: allow, deny, modify, require_approval",
    )
    reason: str = Field(
        default="",
        description="Policy justification or violation details",
    )
    modifications: dict[str, Any] | None = Field(
        default=None,
        description="Argument modifications if decision is MODIFY",
    )
    granted_by: str = Field(
        default="policy_kernel",
        description="Subsystem that made the decision (e.g. policy_kernel, standing_grant)",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Decision timestamp",
    )


class ApprovalRequest(BaseContract):
    """Suspended approval request awaiting human or operator confirmation."""

    approval_id: str = Field(
        ...,
        description="Unique approval identifier (e.g. approval_xxx)",
    )
    request_id: str = Field(
        ...,
        description="Originating request ID",
    )
    session_id: str = Field(
        ...,
        description="Target conversation session ID",
    )
    run_id: str | None = Field(
        default=None,
        description="Associated durable run ID",
    )
    kind: str = Field(
        default="tool_confirm",
        description="Approval kind: tool_confirm, handoff, grant",
    )
    prompt: str = Field(
        ...,
        description="Human-readable prompt displayed to the user",
    )
    options: list[str] = Field(
        default_factory=lambda: ["once", "deny"],
        description="Valid decision options",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool name, arguments, and risk classification",
    )
    status: Literal["pending", "approved", "denied", "expired"] = Field(
        default="pending",
        description="Resolution status",
    )
    decision: str | None = Field(
        default=None,
        description="Operator selected decision (e.g. once, deny, always)",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Creation timestamp",
    )
    resolved_at: float | None = Field(
        default=None,
        description="Resolution timestamp",
    )


class EffectIntent(BaseContract):
    """Durable declaration of an intended side effect before execution."""

    effect_id: str = Field(
        default_factory=lambda: f"eff_{uuid.uuid4().hex[:12]}",
        description="Unique effect identifier",
    )
    request_id: str = Field(
        ...,
        description="Associated request ID",
    )
    run_id: str = Field(
        ...,
        description="Associated durable run ID",
    )
    proposal_id: str = Field(
        ...,
        description="Associated proposal ID",
    )
    authority_decision_id: str = Field(
        ...,
        description="Authorizing decision ID",
    )
    idempotency_key: str = Field(
        ...,
        description="Stable key preventing duplicate execution (e.g. hash of op+target)",
    )
    action: str = Field(
        ...,
        description="Action operation descriptor",
    )
    target: str = Field(
        ...,
        description="Target resource or entity",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Effect arguments / mutation parameters",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Intent declaration timestamp",
    )


class EffectStatus(str, Enum):
    APPLIED = "applied"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class EffectResult(BaseContract):
    """Outcome recorded in the EffectLedger after execution."""

    effect_id: str = Field(
        ...,
        description="Target effect identifier",
    )
    status: EffectStatus = Field(
        ...,
        description="Execution status",
    )
    result: Any = Field(
        default=None,
        description="Raw execution return value or output",
    )
    error: str | None = Field(
        default=None,
        description="Error details if execution failed",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Completion timestamp",
    )


class VerificationStatus(str, Enum):
    OBJECTIVE_VERIFIED = "objective_verified"
    OBJECTIVE_FAILED = "objective_failed"
    OBJECTIVE_INCONCLUSIVE = "objective_inconclusive"


class VerificationResult(BaseContract):
    """Independent verification asserting whether an objective succeeded."""

    verification_id: str = Field(
        default_factory=lambda: f"verif_{uuid.uuid4().hex[:12]}",
        description="Unique verification identifier",
    )
    request_id: str = Field(
        ...,
        description="Associated request ID",
    )
    run_id: str | None = Field(
        default=None,
        description="Associated run ID",
    )
    effect_id: str | None = Field(
        default=None,
        description="Associated effect ID",
    )
    status: VerificationStatus = Field(
        ...,
        description="Verification outcome",
    )
    target_objective: str = Field(
        ...,
        description="Objective text or claim verified",
    )
    evidence: str = Field(
        ...,
        description="Independent evidence string (e.g. disk probe, port check)",
    )
    verifier: str = Field(
        ...,
        description="Verifier identifier or method used",
    )
    error: str | None = Field(
        default=None,
        description="Error observed during verification",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Verification timestamp",
    )


# ── Attachments & Perception ─────────────────────────────────────────────────────


class Attachment(BaseContract):
    """Structured file or media attachment associated with a session."""

    attachment_id: str = Field(
        default_factory=lambda: f"att_{uuid.uuid4().hex[:12]}",
        description="Unique attachment identifier",
    )
    session_id: str = Field(
        ...,
        description="Target session ID",
    )
    original_filename: str = Field(
        ...,
        description="Original client filename",
    )
    stored_filename: str = Field(
        ...,
        description="Sanitized unique filename on disk",
    )
    safe_path: str = Field(
        ...,
        description="Absolute filesystem path to persisted attachment file",
    )
    mime_type: str = Field(
        default="application/octet-stream",
        description="MIME classification",
    )
    size_bytes: int = Field(
        ...,
        ge=0,
        description="File size in bytes",
    )
    sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 digest of file content",
    )
    is_image: bool = Field(
        default=False,
        description="Whether this attachment is an image for multimodal vision",
    )
    provenance: str = Field(
        default="remote_upload",
        description="Source of attachment (e.g. remote_upload, local_paste)",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Upload timestamp",
    )


# ── Capabilities, Models & Providers ─────────────────────────────────────────────


class Capability(BaseContract):
    """Programmable capability package manifest."""

    capability_id: str = Field(
        ...,
        description="Unique capability identifier (e.g. cap.filesystem.read)",
    )
    name: str = Field(
        ...,
        description="Human-readable capability name",
    )
    version: str = Field(
        default="1.0.0",
        description="Semantic version string",
    )
    category: Literal["script", "skill", "integration", "workflow", "tool_adapter", "device_adapter"] = Field(
        default="skill",
        description="Capability category",
    )
    description: str = Field(
        default="",
        description="Capability function description",
    )
    permissions: list[str] = Field(
        default_factory=list,
        description="Permissions required by this capability",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Tools exposed by this capability",
    )
    certified_roles: list[str] = Field(
        default_factory=list,
        description="Certified cognitive roles (e.g. REACT, CHAT, VISION)",
    )
    preconditions: list[str] = Field(
        default_factory=list,
        description="Environmental preconditions required for execution",
    )
    rollback_strategy: str | None = Field(
        default=None,
        description="Strategy to revert side effects",
    )
    provenance: str = Field(
        default="built_in",
        description="Provenance of capability: built_in, operator_installed, agent_created",
    )


class Provider(BaseContract):
    """Cognition provider record in the runtime inventory."""

    provider_id: str = Field(
        ...,
        description="Canonical provider identifier (e.g. ollama, ollama-cloud, anthropic)",
    )
    name: str = Field(
        ...,
        description="Display name",
    )
    endpoint: str = Field(
        ...,
        description="Base URL or socket endpoint",
    )
    status: Literal["online", "offline", "unconfigured", "degraded"] = Field(
        default="offline",
        description="Current connectivity status",
    )
    authenticated: bool = Field(
        default=False,
        description="Whether required credentials/tokens are available",
    )
    reachable: bool = Field(
        default=False,
        description="Whether endpoint responds to health probes",
    )
    certified: bool = Field(
        default=False,
        description="Whether provider is verified against certification suite",
    )
    models: list[str] = Field(
        default_factory=list,
        description="Model IDs advertised by this provider",
    )


class Model(BaseContract):
    """Cognition model specification and capability profile."""

    model_id: str = Field(
        ...,
        description="Canonical model identifier (e.g. kimi-k2.7-code:cloud)",
    )
    name: str = Field(
        ...,
        description="Display name",
    )
    provider_id: str = Field(
        ...,
        description="Parent provider identifier",
    )
    capabilities: list[str] = Field(
        default_factory=lambda: ["completion"],
        description="Model features: tools, vision, thinking, completion",
    )
    certified_roles: list[str] = Field(
        default_factory=list,
        description="Certified roles: CHAT, REACT, PLANNING, CRITIC, VISION",
    )
    context_length: int = Field(
        default=8192,
        ge=1024,
        description="Maximum token context window",
    )
    multimodal: bool = Field(
        default=False,
        description="Whether model natively accepts image inputs",
    )
    tool_use: bool = Field(
        default=True,
        description="Whether model supports structured tool-calling",
    )


# ── Devices & Multi-Agent ────────────────────────────────────────────────────────


class Device(BaseContract):
    """Generic client node or embodiment connected to the Gateway."""

    device_id: str = Field(
        ...,
        description="Unique device identifier",
    )
    owner_entity: str = Field(
        ...,
        description="Owning Entity ID",
    )
    name: str = Field(
        ...,
        description="Device display name (e.g. Matthew's iPhone)",
    )
    device_type: Literal["mac", "web", "phone", "vision_pro", "robot", "sensor", "cli"] = Field(
        default="web",
        description="Device hardware classification",
    )
    connection_state: Literal["connected", "disconnected", "reconnecting", "stale"] = Field(
        default="connected",
        description="Current connection state",
    )
    transport: Literal["websocket", "sse", "unix_socket", "rest"] = Field(
        default="rest",
        description="Transport medium",
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="Hardware capabilities: display, microphone, camera, motion, filesystem",
    )
    permissions: list[str] = Field(
        default_factory=list,
        description="Permissions granted to this device",
    )
    health: dict[str, Any] = Field(
        default_factory=dict,
        description="Device telemetry and battery/CPU health metrics",
    )
    last_seen: float = Field(
        default_factory=time.time,
        description="Last heartbeat timestamp",
    )


class AgentToAgentRequest(BaseContract):
    """Structured RPC request between cooperating agents."""

    message_id: str = Field(
        default_factory=lambda: f"a2a_{uuid.uuid4().hex[:12]}",
        description="Unique message identifier",
    )
    source_agent_id: str = Field(
        ...,
        description="Sender agent ID",
    )
    target_agent_id: str = Field(
        ...,
        description="Recipient agent ID",
    )
    task_type: str = Field(
        ...,
        description="Requested task classification",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Task input data and parameters",
    )
    delegation_depth: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Current delegation depth to prevent infinite loops",
    )
    timeout_s: float = Field(
        default=60.0,
        gt=0.0,
        description="Execution timeout in seconds",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Message dispatch timestamp",
    )


class AgentToAgentResult(BaseContract):
    """Structured RPC result from a cooperating agent."""

    message_id: str = Field(
        default_factory=lambda: f"a2a_res_{uuid.uuid4().hex[:12]}",
        description="Unique response message identifier",
    )
    correlation_id: str = Field(
        ...,
        description="Originating AgentToAgentRequest message_id",
    )
    source_agent_id: str = Field(
        ...,
        description="Responding agent ID",
    )
    status: Literal["completed", "failed", "rejected", "timed_out"] = Field(
        default="completed",
        description="Execution outcome",
    )
    result: Any = Field(
        default=None,
        description="Task outcome payload",
    )
    error: str | None = Field(
        default=None,
        description="Error details if execution failed",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Response timestamp",
    )
