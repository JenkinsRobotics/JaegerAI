"""jaeger-models: ModelCatalog, ModelRouter, StickyFallbackModel, Telemetry, Risk Cards & Evals."""

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
from .model_risk import (
    RISK_FLAG_CATALOG,
    DetectedFlag,
    EvalCandidate,
    ModelEvalSuite,
    ModelRiskCard,
    RiskFlagSpec,
    build_static_risk_card,
)
from .overlay import current_model_overlay, model_overlay, resolve_overlaid_model
from .provider_telemetry import (
    ModelPricing,
    ModelUsageLedger,
    RateLimitSnapshot,
    estimate_model_pricing,
    fetch_ollama_cloud_telemetry,
    fetch_openrouter_telemetry,
    parse_rate_limit_headers,
)
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
    "DetectedFlag",
    "EvalCandidate",
    "FitEvaluation",
    "HardwareProfile",
    "HybridRoutingConfig",
    "HybridRoutingStore",
    "ModelCatalog",
    "ModelEvalSuite",
    "ModelPricing",
    "ModelRecipe",
    "ModelRequestAttempt",
    "ModelRiskCard",
    "ModelRoundtable",
    "ModelRouter",
    "ModelUsageLedger",
    "OllamaModel",
    "OpenAICompatModel",
    "ParticipantResponse",
    "RISK_FLAG_CATALOG",
    "RateLimitSnapshot",
    "ReplayModel",
    "ResponseFold",
    "RiskFlagSpec",
    "RoundtableParticipant",
    "RoundtableReport",
    "SUPPORTED_MODALITIES",
    "StickyFallbackModel",
    "benchmark_model",
    "build_default_model",
    "build_static_risk_card",
    "estimate_model_pricing",
    "evaluate_recipe_fit",
    "fetch_ollama_cloud_telemetry",
    "fetch_openrouter_telemetry",
    "host_total_memory_gb",
    "parse_rate_limit_headers",
    "probe_hardware",
    "recommend_models",
    "safe_local_context_window",
]
