"""Swappable @runtime_checkable Protocol ports for all 8 JaegerAI core modules."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from .types import (
    ActionProposal,
    EventEnvelope,
    ModelProfile,
    PolicyVerdict,
    SandboxProfile,
    SandboxSpec,
    ToolResult,
)


@runtime_checkable
class ModelPort(Protocol):
    """01-models: provider-agnostic LLM client + capability profile contract."""

    @property
    def name(self) -> str: ...
    def profile(self, model_id: str) -> ModelProfile: ...
    def complete(self, messages: Sequence[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]: ...


@runtime_checkable
class ToolPort(Protocol):
    """02-tools: tool registration, progressive discovery, and execution contract."""

    @property
    def name(self) -> str: ...
    def list_tools(self, *, query: str | None = None) -> Sequence[Mapping[str, Any]]: ...
    def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> ToolResult: ...


@runtime_checkable
class ExecutionLoopPort(Protocol):
    """03-execution-loop: composable turn execution contract."""

    @property
    def name(self) -> str: ...
    def run_turn(self, prompt: str, *, max_steps: int = 20) -> Mapping[str, Any]: ...


@runtime_checkable
class StateMemoryPort(Protocol):
    """04-state-and-memory: persistence, checkpointing, and context compaction contract."""

    @property
    def name(self) -> str: ...
    def save_checkpoint(self, session_id: str, state: Mapping[str, Any]) -> str: ...
    def load_checkpoint(self, checkpoint_id: str) -> Mapping[str, Any] | None: ...
    def compact(self, messages: Sequence[Mapping[str, Any]], *, max_tokens: int) -> list[dict[str, Any]]: ...


@runtime_checkable
class PolicyPort(Protocol):
    """05-permissions-and-sandbox (Policy): deterministic fail-closed authority gate."""

    @property
    def name(self) -> str: ...
    def evaluate(self, proposal: ActionProposal, *, dry_run: bool = False) -> PolicyVerdict: ...


@runtime_checkable
class SandboxPort(Protocol):
    """05-permissions-and-sandbox (Sandbox): OS/container execution boundary."""

    @property
    def name(self) -> str: ...
    def prepare(self, command: Sequence[str], profile: SandboxProfile) -> SandboxSpec: ...


@runtime_checkable
class OrchestrationPort(Protocol):
    """06-orchestration: subagent delegation, permission intersection, and mailboxes."""

    @property
    def name(self) -> str: ...
    def spawn(self, task: str, *, role: str, parent_profile: SandboxProfile | None = None) -> str: ...
    def await_result(self, agent_id: str) -> Mapping[str, Any]: ...


@runtime_checkable
class ReliabilityPort(Protocol):
    """07-reliability: error classification, argument repair, and stuck-loop detection."""

    @property
    def name(self) -> str: ...
    def classify_error(self, error: Exception) -> str: ...
    def repair_arguments(self, tool_name: str, raw_args: Any, schema: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def check_loop(self, history: Sequence[Mapping[str, Any]]) -> bool: ...


@runtime_checkable
class EventBusPort(Protocol):
    """08-events: typed, sequenced, replay-safe event bus contract."""

    @property
    def name(self) -> str: ...
    def publish(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        session_id: str = "default",
        durable: bool = True,
    ) -> EventEnvelope: ...
    def subscribe(
        self,
        event_type: str,
        handler: Callable[[EventEnvelope], None],
        *,
        skip_on_replay: bool = False,
    ) -> Callable[[], None]: ...


PORT_PROTOCOLS: dict[str, type] = {
    "01-models": ModelPort,
    "02-tools": ToolPort,
    "03-execution-loop": ExecutionLoopPort,
    "04-state-and-memory": StateMemoryPort,
    "05-policy": PolicyPort,
    "05-sandbox": SandboxPort,
    "06-orchestration": OrchestrationPort,
    "07-reliability": ReliabilityPort,
    "08-events": EventBusPort,
}
