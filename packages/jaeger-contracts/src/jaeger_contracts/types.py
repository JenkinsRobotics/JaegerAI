"""Zero-dependency typed domain models shared across all standalone Jaeger modules."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class AutonomyMode(str, Enum):
    """Execution posture controlling how autonomously an agent may act."""

    READ_ONLY = "read_only"
    ASK_ON_WRITE = "ask_on_write"
    WORKSPACE_SANDBOX = "workspace_sandbox"
    FULL_ACCESS = "full_access"


class DecisionKind(str, Enum):
    """Canonical four-way authority outcome (1:1 with JaegerAI PolicyKernel)."""

    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class ActionProposal:
    """Normalized action proposed by cognition prior to execution."""

    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    workspace: Path = field(default_factory=lambda: Path.cwd())
    actor: str = "owner:local"
    session_id: str = "default"
    proposal_id: str = field(default_factory=lambda: f"prop_{uuid.uuid4().hex[:12]}")
    target_path: str | None = None
    action_type: str = "tool_call"
    tier: str = "write_local"  # read_only | write_local | external_effect | hardware | privileged
    autonomy_mode: AutonomyMode = AutonomyMode.WORKSPACE_SANDBOX
    tool_source: str = "builtin"
    sandboxed: bool = True
    context: Mapping[str, Any] = field(default_factory=dict)
    proposed_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PolicyVerdict:
    """Deterministic fail-closed judgment produced by any PolicyPort."""

    decision: DecisionKind
    reason: str = ""
    policy_name: str = "policy_engine"
    granted_by: str = "policy_engine"
    authorized_arguments: Mapping[str, Any] | None = None
    decision_id: str = field(default_factory=lambda: f"auth_{uuid.uuid4().hex[:12]}")
    proposal_id: str = ""
    inspector_chain: tuple[str, ...] = ()
    trace: tuple[Mapping[str, Any], ...] = ()
    evaluated_at: float = field(default_factory=time.time)

    @property
    def is_authorized(self) -> bool:
        return self.decision in (DecisionKind.ALLOW, DecisionKind.MODIFY)


@dataclass(frozen=True)
class SandboxProfile:
    """Declarative OS/container confinement boundary."""

    workspace: Path
    writable_roots: tuple[Path, ...] = ()
    read_only_subpaths: tuple[Path, ...] = ()
    denied_read_paths: tuple[Path, ...] = ()
    denied_write_paths: tuple[Path, ...] = ()
    allow_network: bool = False
    allow_tmp_writes: bool = True
    read_only_default: bool = True


@dataclass(frozen=True)
class SandboxSpec:
    """Prepared argv and confinement assertions returned by a SandboxPort."""

    backend: str
    argv: tuple[str, ...]
    read_only_default: bool
    protects_workspace_boundary: bool
    protects_git_metadata: bool
    protects_secret_stores: bool
    profile_text: str = ""


@dataclass(frozen=True)
class EventEnvelope:
    """Typed, monotonically sequenced event for replay-safe streams and OTLP export."""

    seq: int
    event_type: str
    payload: Mapping[str, Any]
    session_id: str = "default"
    trace_id: str = ""
    span_id: str = ""
    durable: bool = True
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ModelProfile:
    """Declarative model capability descriptor (decoupled from provider wire SDK)."""

    model_id: str
    provider: str
    context_window: int
    max_output_tokens: int = 8192
    supports_native_tools: bool = True
    supports_structured_output: bool = True
    supports_prompt_caching: bool = False
    supports_reasoning: bool = False
    local_only: bool = False


@dataclass(frozen=True)
class ToolResult:
    """Normalized result returned by any ToolPort execution."""

    tool_name: str
    ok: bool
    output: str = ""
    error: str | None = None
    truncated: bool = False
    offload_path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
