"""jaeger-models: ModelCatalog, ModelRouter, StickyFallbackModel, ReplayModel & live HTTP providers."""

from . import cache_health, overlay, reasoning_tags
from .cache_health import CacheCollapseEvent, ConversationCacheMarkStore
from .catalog import BUILTIN_PROFILES, ModelCatalog
from .hybrid_routing import HybridRoutingConfig, HybridRoutingStore
from .local_budget import host_total_memory_gb, safe_local_context_window
from .overlay import current_model_overlay, model_overlay, resolve_overlaid_model
from .providers import (
    AnthropicModel,
    OllamaModel,
    OpenAICompatModel,
    StreamSink,
    bind_stream_sink,
    build_default_model,
)
from .reasoning_tags import remove_reasoning_content, replace_reasoning_tags
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
    "HybridRoutingConfig",
    "HybridRoutingStore",
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
