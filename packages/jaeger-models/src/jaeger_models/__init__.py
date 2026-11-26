"""jaeger-models: ModelCatalog, ModelRouter, StickyFallbackModel, ReplayModel & live HTTP providers."""

from .catalog import BUILTIN_PROFILES, ModelCatalog
from .local_budget import host_total_memory_gb, safe_local_context_window
from .providers import (
    AnthropicModel,
    OllamaModel,
    OpenAICompatModel,
    build_default_model,
)
from .router import (
    CallableModel,
    ModelRequestAttempt,
    ModelRouter,
    ReplayModel,
    ResponseFold,
    StickyFallbackModel,
)

__all__ = [
    "AnthropicModel",
    "BUILTIN_PROFILES",
    "CallableModel",
    "ModelCatalog",
    "ModelRequestAttempt",
    "ModelRouter",
    "OllamaModel",
    "OpenAICompatModel",
    "ReplayModel",
    "ResponseFold",
    "StickyFallbackModel",
    "build_default_model",
    "host_total_memory_gb",
    "safe_local_context_window",
]
