"""JaegerAI Model Subsystem — Architecture for Advanced Agent Framework.

This package organizes all model capabilities into four clear, cohesive pillars
designed for new coders to easily understand and extend:

1. ROUTING & PRIVACY GOVERNANCE (`jaeger_ai.core.models.router`):
   - ModelRouter: Main coordinator for model resolution, privacy gating, and endpoints.
   - SensitivityGate & SensitivityDecision: Classifies prompt sensitivity (private vs public),
     enforces zero-leak local execution for sensitive data, and maintains audit trails.
   - EndpointResolver: Resolves local Ollama / LM Studio daemons or container-to-host bridges.
   - select_client: Dynamically switches models per session turn.

2. DISCOVERY (`jaeger_ai.core.models.discovery`):
   - discover_all: Surveys disk GGUF/MLX models, local servers, and cloud catalogs.
   - discover_local_gguf_files / discover_local_mlx: Scans filesystem for offline weights.
   - discover_ollama / discover_lmstudio: Probes local servers cleanly without exceptions.

3. RESOLUTION & REGISTRATION (`jaeger_ai.core.models.model_resolver`, `engine_registry`):
   - resolve_model / list_registered_models: Maps model keys to weights and profiles.
   - resolve_engine: Selects optimal inference engine for hardware and format.

4. EXECUTION CLIENTS (`jaeger_ai.core.models.external_model`, `mlx_client`):
   - ExternalModelClient: Universal OpenAI / Anthropic / Ollama HTTP client.
   - MlxClient / MlxVlmClient: Native Apple Silicon MLX execution.
   - load_history / recent_models / record_use: Per-provider model usage history.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    # 1. Routing & Privacy
    "ModelRouter",
    "SensitivityGate",
    "SensitivityDecision",
    "EndpointResolver",
    "apply_sensitivity_routing",
    "decide",
    "normalize_ollama_provider",
    "resolve_ollama_base_url",
    "select_client",
    # 2. Discovery
    "DiscoveredModel",
    "discover_all",
    "discover_jaeger",
    "discover_local_gguf",
    "discover_local_gguf_files",
    "discover_local_mlx",
    "discover_local_ollama_models",
    "discover_lmstudio",
    "discover_ollama",
    "discover_ollama_cloud",
    "scan_paths",
    # 3. Resolution & Registry
    "list_registered_models",
    "resolve_model",
    # 4. Execution Clients & History
    "ExternalModelClient",
    "ExternalModelError",
    "ExternalModelSelectionError",
    "MlxClient",
    "MlxVlmClient",
    "load_history",
    "recent_models",
    "record_use",
]

_EXPORTS: dict[str, str] = {
    "ModelRouter": "jaeger_ai.core.models.router",
    "SensitivityGate": "jaeger_ai.core.models.router",
    "SensitivityDecision": "jaeger_ai.core.models.router",
    "EndpointResolver": "jaeger_ai.core.models.router",
    "apply_sensitivity_routing": "jaeger_ai.core.models.router",
    "decide": "jaeger_ai.core.models.router",
    "normalize_ollama_provider": "jaeger_ai.core.models.router",
    "resolve_ollama_base_url": "jaeger_ai.core.models.router",
    "select_client": "jaeger_ai.core.models.router",
    "DiscoveredModel": "jaeger_ai.core.models.discovery",
    "discover_all": "jaeger_ai.core.models.discovery",
    "discover_jaeger": "jaeger_ai.core.models.discovery",
    "discover_local_gguf": "jaeger_ai.core.models.discovery",
    "discover_local_gguf_files": "jaeger_ai.core.models.discovery",
    "discover_local_mlx": "jaeger_ai.core.models.discovery",
    "discover_local_ollama_models": "jaeger_ai.core.models.discovery",
    "discover_lmstudio": "jaeger_ai.core.models.discovery",
    "discover_ollama": "jaeger_ai.core.models.discovery",
    "discover_ollama_cloud": "jaeger_ai.core.models.discovery",
    "scan_paths": "jaeger_ai.core.models.discovery",
    "list_registered_models": "jaeger_ai.core.models.model_resolver",
    "resolve_model": "jaeger_ai.core.models.model_resolver",
    "ExternalModelClient": "jaeger_ai.core.models.external_model",
    "ExternalModelError": "jaeger_ai.core.models.external_model",
    "ExternalModelSelectionError": "jaeger_ai.core.models.external_model",
    "MlxClient": "jaeger_ai.core.models.mlx_client",
    "MlxVlmClient": "jaeger_ai.core.models.mlx_client",
    "load_history": "jaeger_ai.core.models.external_model",
    "recent_models": "jaeger_ai.core.models.external_model",
    "record_use": "jaeger_ai.core.models.external_model",
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        mod = importlib.import_module(_EXPORTS[name])
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
