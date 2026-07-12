"""``ProviderAdapter`` — the contract every backend implements.

Three contracts: format the agent's internal messages into provider-
native shape, perform the actual model call (interruptibly), parse the
provider response back to one internal ``Message``. The agent loop
deals only in this triple — every other concern (HTTP, authentication,
streaming chunks, error retry inside the SDK, prompt caching markers
on Anthropic, the ``<tools>`` block injection on Hermes-XML, in-process
direct call for llama-cpp / MLX) lives entirely inside the adapter.

Deliberately not assuming HTTP. The same ABC is the right shape for an
on-device adapter that calls ``mlx_lm.generate`` directly, or a
ROS-bridged remote-model adapter that publishes on a topic. That
flexibility costs nothing in the loop and unlocks the hardware
deployment story in 0.2 without an architectural change.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any

from jaeger_os.agent.schemas.message_types import Message
from jaeger_os.core.tools.tool_schema import ToolDef


# Features an adapter may declare. Listed here so capability checks
# don't depend on free-form strings.
KNOWN_FEATURES = frozenset({
    "caching",        # provider-side prompt caching (Anthropic)
    "streaming",      # token-level streaming
    "vision",         # image inputs
    "parallel_tools", # multiple tool_calls in one response
    "reasoning",      # extended thinking / chain-of-thought blocks
})


class ProviderAdapter(ABC):
    """Subclass per backend (Anthropic, OpenAI-compatible, Hermes-XML,
    in-process llama-cpp, MLX, …). Three abstract methods plus a
    capability declaration; everything else has a sensible default."""

    name: str = "unnamed"
    """Short identifier used in logs and the ``/runtime`` panel."""

    # ── conversion ───────────────────────────────────────────────────

    @abstractmethod
    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> Any:
        """Convert internal ``Message`` list → provider-native payload.

        Returns whatever shape ``call()`` consumes — opaque to the
        agent loop. Adapters that need separate system / tools fields
        (Anthropic does) embed them here."""

    @abstractmethod
    def call(
        self,
        formatted: Any,
        interrupt_event: threading.Event,
        **kwargs: Any,
    ) -> Any:
        """Run one model request. Must honour ``interrupt_event`` via
        :func:`jaeger_os.agent.loop.interrupt.interruptible_call` (or an
        equivalent pattern) — the operator must be able to halt the
        agent mid-call. Returns the raw provider response object,
        which ``parse_response`` then decodes."""

    @abstractmethod
    def parse_response(self, raw: Any) -> Message:
        """Convert provider-native response → one internal ``Message``.

        The returned message has ``role="assistant"``, plus either
        ``content`` (text answer), ``tool_calls`` (one or more), or
        both. Drift parsing / arg repair / name normalisation
        (necessary for local models that emit malformed JSON) belongs
        inside this method — the agent loop trusts what comes out."""

    # ── capability + health ──────────────────────────────────────────

    @abstractmethod
    def supports(self, feature: str) -> bool:
        """Capability check. ``feature`` is one of :data:`KNOWN_FEATURES`.
        The agent loop uses this to decide e.g. whether to dispatch
        tool calls in parallel."""

    def health_check(self) -> dict[str, Any]:
        """Best-effort reachability probe. Default assumes always-OK
        (correct for in-process backends); HTTP adapters override to
        ping the endpoint. Returns ``{"ok": bool, "detail": str,
        "latency_s": float}``."""
        return {"ok": True, "detail": "no health check implemented", "latency_s": 0.0}

    def describe(self) -> str:
        """One-line label for logs and the active-brain status line."""
        return f"{self.__class__.__name__}({self.name})"


__all__ = ["ProviderAdapter", "KNOWN_FEATURES"]
