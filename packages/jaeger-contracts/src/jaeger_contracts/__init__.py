"""jaeger-contracts: zero-dependency pure wire envelopes and local Python SPIs.

Mutable runtime composition (``ModuleRegistry``) lives in the product/Gateway
composition root (``jaeger_ai.core.runtime.composition``), keeping this spine
pure, stateless, and free of runtime side effects.
"""

from .ports import (
    PORT_PROTOCOLS,
    EventBusPort,
    ExecutionLoopPort,
    ModelPort,
    OrchestrationPort,
    PolicyPort,
    ReliabilityPort,
    SandboxPort,
    StateMemoryPort,
    ToolPort,
)
from .types import (
    ActionProposal,
    AutonomyMode,
    DecisionKind,
    EventEnvelope,
    ModelProfile,
    PolicyVerdict,
    SandboxProfile,
    SandboxSpec,
    ToolResult,
)
from .wire import (
    WIRE_SCHEMA_VERSION,
    OperationClass,
    WireActionReceipt,
    WireEnvelope,
)

__all__ = [
    "WIRE_SCHEMA_VERSION",
    "OperationClass",
    "WireActionReceipt",
    "WireEnvelope",
    "ActionProposal",
    "AutonomyMode",
    "DecisionKind",
    "EventBusPort",
    "EventEnvelope",
    "ExecutionLoopPort",
    "ModelPort",
    "ModelProfile",
    "OrchestrationPort",
    "PORT_PROTOCOLS",
    "PolicyPort",
    "PolicyVerdict",
    "ReliabilityPort",
    "SandboxPort",
    "SandboxProfile",
    "SandboxSpec",
    "StateMemoryPort",
    "ToolPort",
    "ToolResult",
]
