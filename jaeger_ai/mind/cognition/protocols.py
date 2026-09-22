"""
ARES SI — ReasoningProvider protocol.

The contract every worker adapter must implement.
No provider-specific code outside the adapter.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import (
    ContextBriefing,
    WorkerResult,
    AvailabilityStatus,
    CostEstimate,
    LatencyProfile,
    WorkerCapability,
)


@runtime_checkable
class ReasoningProvider(Protocol):
    """The contract every worker adapter must implement.

    Workers own execution. They do NOT own identity, memory, policy,
    or the user relationship. They receive a ContextBriefing and
    return a WorkerResult. That is the entire contract.
    """

    # Identity
    worker_id: str              # e.g. "claude-code", "ollama-llama3"
    provider: str               # e.g. "anthropic", "local"
    display_name: str           # e.g. "Claude Code", "Llama 3 (local)"
    capabilities: list[WorkerCapability]
    privacy_class: str          # "local_only", "approved_provider", "external_provider"
    data_location: str          # "local" or "cloud"
    context_limit: int | None   # Max tokens, None = unlimited

    # Execution
    async def generate(
        self,
        briefing: ContextBriefing,
        message: str,
        **kwargs: Any,
    ) -> WorkerResult:
        """Execute a task with the given briefing and user message.

        The briefing contains ONLY what the SI has decided to share,
        filtered by the Trust Engine and budgeted by the Context Compiler.
        The worker must not attempt to access the Journal directly.
        """
        ...

    # Capability declaration
    def supports_streaming(self) -> bool:
        """Whether this worker supports streaming responses."""
        ...

    def supports_files(self) -> bool:
        """Whether this worker can process file attachments."""
        ...

    def supports_images(self) -> bool:
        """Whether this worker can process image attachments."""
        ...

    def supports_tools(self, tool_ids: list[str]) -> bool:
        """Whether this worker supports the specified tools."""
        ...

    # Health
    async def check_availability(self) -> AvailabilityStatus:
        """Check if this worker is currently reachable."""
        ...

    def estimated_cost(self, tokens: int) -> CostEstimate:
        """Estimate the cost for processing the given number of tokens."""
        ...

    def estimated_latency(self) -> LatencyProfile:
        """Get expected latency characteristics."""
        ...