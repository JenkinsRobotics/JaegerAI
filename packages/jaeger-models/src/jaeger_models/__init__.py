"""jaeger-models: ModelCatalog, ModelRouter, StickyFallbackModel, and ReplayModel."""

from .catalog import BUILTIN_PROFILES, ModelCatalog
from .local_budget import host_total_memory_gb, safe_local_context_window
from .router import CallableModel, ModelRouter, ReplayModel, StickyFallbackModel

__all__ = [
    "BUILTIN_PROFILES",
    "CallableModel",
    "ModelCatalog",
    "ModelRouter",
    "ReplayModel",
    "StickyFallbackModel",
    "host_total_memory_gb",
    "safe_local_context_window",
]
