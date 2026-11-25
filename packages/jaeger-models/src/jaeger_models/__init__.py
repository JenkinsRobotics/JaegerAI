"""jaeger-models: ModelCatalog, ModelRouter, StickyFallbackModel, and ReplayModel."""

from .catalog import BUILTIN_PROFILES, ModelCatalog
from .local_budget import host_total_memory_gb, safe_local_context_window
from .router import (
    CallableModel,
    ModelRequestAttempt,
    ModelRouter,
    ReplayModel,
    ResponseFold,
    StickyFallbackModel,
)

__all__ = [
    "BUILTIN_PROFILES",
    "CallableModel",
    "ModelCatalog",
    "ModelRequestAttempt",
    "ModelRouter",
    "ReplayModel",
    "ResponseFold",
    "StickyFallbackModel",
    "host_total_memory_gb",
    "safe_local_context_window",
]
