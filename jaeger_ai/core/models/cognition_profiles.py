"""Cognition Profiles and Canonical Provider Inventory (Workstream 14).

Formalizes:
1. The 8 Provider Lifecycle States:
   - SUPPORTED
   - CONFIGURED
   - CREDENTIALS_AVAILABLE
   - REACHABLE
   - DISCOVERED
   - CERTIFIED
   - AUTHORIZED
   - ACTIVE

2. Model Cognition Profiles:
   - provider & endpoint type
   - modality & context length
   - tool-call format & parallel tool support
   - vision & reasoning behavior
   - latency & cost class
   - certified roles & formatting preferences

3. Invariant:
   Provider swap must preserve Agent identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any, Literal

logger = logging.getLogger("jaeger.core.models.cognition_profiles")


class ProviderStatus(str, Enum):
    """The explicit states of a provider."""
    SUPPORTED = "supported"                     # Implemented in code
    CONFIGURED = "configured"                   # Present in config or instance setup
    CREDENTIALS_AVAILABLE = "credentials_avail" # API key or socket present
    REACHABLE = "reachable"                     # Network/daemon probe succeeds
    DISCOVERED = "discovered"                   # Models queried successfully
    CERTIFIED = "certified"                     # Passed quality/eval benchmarks
    AUTHORIZED = "authorized"                   # Permitted by operator policy
    ACTIVE = "active"                           # Currently serving runtime turn


@dataclass(frozen=True)
class ProviderAssessment:
    """Full 8-dimension assessment of a cognition provider."""
    provider_id: str
    display_name: str
    supported: bool = True
    configured: bool = False
    credentials_available: bool = False
    reachable: bool = False
    discovered: bool = False
    certified: bool = False
    authorized: bool = True
    active: bool = False
    error: str | None = None

    @property
    def is_operational(self) -> bool:
        """Operational if credentials available, reachable, and authorized."""
        return self.credentials_available and self.reachable and self.authorized


@dataclass(frozen=True)
class CognitionProfile:
    """Detailed profile governing model behavior and cognitive presentation."""
    model_id: str
    provider_id: str
    endpoint_type: str = "openai_compatible"  # ollama, openai, anthropic, gemini, mlx
    modality: tuple[str, ...] = ("text",)
    context_length: int = 8192
    tool_call_format: str = "openai_function_call"  # openai_function_call, hermes_tags, json_xml
    parallel_tool_support: bool = True
    vision: bool = False
    reasoning_behavior: str = "standard"  # standard, extended_thinking, deliberate_react
    latency_class: str = "medium"         # low, medium, high
    cost_class: str = "cloud_medium"      # local_free, cloud_low, cloud_medium, cloud_high
    certified_roles: tuple[str, ...] = ("CHAT",)
    tool_surface_preferences: dict[str, Any] = field(default_factory=dict)
    context_format_preferences: dict[str, Any] = field(default_factory=dict)


# Canonical profiles for proven baseline models
BUILTIN_COGNITION_PROFILES: dict[str, CognitionProfile] = {
    "kimi-k2.7-code:cloud": CognitionProfile(
        model_id="kimi-k2.7-code:cloud",
        provider_id="ollama-cloud",
        endpoint_type="ollama",
        modality=("text", "vision"),
        context_length=32768,
        tool_call_format="openai_function_call",
        parallel_tool_support=True,
        vision=True,
        reasoning_behavior="deliberate_react",
        latency_class="low",
        cost_class="cloud_low",
        certified_roles=("CHAT", "REACT", "VISION", "PLANNING"),
        tool_surface_preferences={"prefer_compact_schema": True},
        context_format_preferences={"include_provenance": True},
    ),
    "qwen2.5-coder:7b": CognitionProfile(
        model_id="qwen2.5-coder:7b",
        provider_id="ollama-local",
        endpoint_type="ollama",
        modality=("text",),
        context_length=16384,
        tool_call_format="openai_function_call",
        parallel_tool_support=False,
        vision=False,
        reasoning_behavior="standard",
        latency_class="low",
        cost_class="local_free",
        certified_roles=("CHAT", "REACT"),
    ),
    "claude-3-7-sonnet-20250219": CognitionProfile(
        model_id="claude-3-7-sonnet-20250219",
        provider_id="anthropic",
        endpoint_type="anthropic",
        modality=("text", "vision"),
        context_length=200000,
        tool_call_format="anthropic_tools",
        parallel_tool_support=True,
        vision=True,
        reasoning_behavior="extended_thinking",
        latency_class="medium",
        cost_class="cloud_high",
        certified_roles=("CHAT", "REACT", "VISION", "PLANNING", "CRITIC"),
    ),
    "gpt-4o": CognitionProfile(
        model_id="gpt-4o",
        provider_id="openai",
        endpoint_type="openai",
        modality=("text", "vision"),
        context_length=128000,
        tool_call_format="openai_function_call",
        parallel_tool_support=True,
        vision=True,
        reasoning_behavior="standard",
        latency_class="low",
        cost_class="cloud_medium",
        certified_roles=("CHAT", "REACT", "VISION", "PLANNING"),
    ),
}


class CognitionProfileRegistry:
    """Canonical registry mapping models to their cognition profiles."""

    def __init__(self) -> None:
        self._profiles = dict(BUILTIN_COGNITION_PROFILES)

    def get_profile(self, model_name: str, provider_id: str = "") -> CognitionProfile:
        norm = model_name.strip().removeprefix("@")
        if ":" in norm and not norm.startswith("cloud:"):
            # Check if has provider prefix e.g. ollama-cloud:kimi-k2.7-code:cloud
            parts = norm.split(":", 1)
            if parts[0] in ("ollama", "ollama-cloud", "ollama-local", "openai", "anthropic", "gemini", "xai"):
                norm = parts[1]

        if norm in self._profiles:
            return self._profiles[norm]

        # Dynamic profile generation
        is_vision = any(v in norm.lower() for v in ("vision", "4o", "flash", "vl"))
        is_cloud = provider_id.startswith("cloud") or provider_id in ("openai", "anthropic", "gemini", "xai")
        return CognitionProfile(
            model_id=norm,
            provider_id=provider_id or "ollama-local",
            modality=("text", "vision") if is_vision else ("text",),
            context_length=32768 if is_cloud else 8192,
            vision=is_vision,
            cost_class="cloud_medium" if is_cloud else "local_free",
            certified_roles=("CHAT", "REACT") if "coder" in norm.lower() or is_cloud else ("CHAT",),
        )

    def register_profile(self, profile: CognitionProfile) -> None:
        self._profiles[profile.model_id] = profile


def swap_cognition_provider(
    runtime: Any,
    new_provider: str,
    new_model: str,
) -> tuple[bool, str]:
    """Switch runtime cognition provider/model while strictly preserving Entity Identity.

    Invariant:
    Provider swap alters cognition strategy and client, NEVER entity_id or persistent memory.
    """
    original_entity_id = runtime.identity.entity_id
    original_display_name = runtime.identity.display_name

    logger.info(
        "Initiating provider swap for %s: %s -> %s (%s)",
        original_display_name,
        original_entity_id,
        new_provider,
        new_model,
    )

    # Reconfigure model client in runtime layout
    if getattr(runtime, "layout", None) is not None:
        try:
            from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
            cfg = load_yaml(runtime.layout.config_path, Config)
            cfg.external_model.provider = new_provider
            cfg.external_model.model = new_model
            dump_yaml(runtime.layout.config_path, cfg)
        except Exception as exc:
            return False, f"Failed updating instance config: {exc}"

    # Invariant Check: Identity is immutable across provider swap
    assert runtime.identity.entity_id == original_entity_id
    assert runtime.identity.display_name == original_display_name

    return True, f"Successfully switched to {new_provider}:{new_model} preserving entity {original_entity_id}"
