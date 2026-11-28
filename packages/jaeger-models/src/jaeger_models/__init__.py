"""jaeger-models: ModelCatalog, ModelRouter, StickyFallbackModel, ReplayModel & live HTTP providers."""

from . import cache_health, overlay, reasoning_tags
from .cache_health import CacheCollapseEvent, ConversationCacheMarkStore
from .catalog import BUILTIN_PROFILES, ModelCatalog
from .hybrid_routing import HybridRoutingConfig, HybridRoutingStore
from .hwfit import (
    BUILTIN_COOKBOOK,
    SUPPORTED_MODALITIES,
    FitEvaluation,
    HardwareProfile,
    ModelRecipe,
    benchmark_model,
    evaluate_recipe_fit,
    probe_hardware,
    recommend_models,
)
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
from .roundtable import (
    ModelRoundtable,
    ParticipantResponse,
    RoundtableParticipant,
    RoundtableReport,
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
    "BUILTIN_COOKBOOK",
    "BUILTIN_PROFILES",
    "CallableModel",
    "FitEvaluation",
    "HardwareProfile",
    "HybridRoutingConfig",
    "HybridRoutingStore",
    "ModelCatalog",
    "ModelRecipe",
    "ModelRequestAttempt",
    "ModelRoundtable",
    "ModelRouter",
    "OllamaModel",
    "OpenAICompatModel",
    "ParticipantResponse",
    "ReplayModel",
    "ResponseFold",
    "RoundtableParticipant",
    "RoundtableReport",
    "SUPPORTED_MODALITIES",
    "StickyFallbackModel",
    "benchmark_model",
    "build_default_model",
    "evaluate_recipe_fit",
    "host_total_memory_gb",
    "probe_hardware",
    "recommend_models",
    "safe_local_context_window",
]
