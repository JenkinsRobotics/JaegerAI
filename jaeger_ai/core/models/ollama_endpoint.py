"""Ollama endpoint discovery and provider normalization shim.

For full routing, gating, and model selection logic, see :mod:`jaeger_ai.core.models.router`.
This file is maintained for backward compatibility.
"""

from __future__ import annotations

import sys
from jaeger_ai.core.models import router
from jaeger_ai.core.models.router import normalize_ollama_provider

# Expose internal hooks for existing unit test monkeypatching
_reachable = router._reachable
_container_bridge_host = router._container_bridge_host
_running_in_container = router._running_in_container


def resolve_ollama_base_url(*, openai_compat: bool = True) -> str:
    """Resolve Ollama base URL, respecting any module-level monkeypatches."""
    mod = sys.modules[__name__]
    if mod._reachable is not router._reachable:
        router._reachable = mod._reachable
    if mod._container_bridge_host is not router._container_bridge_host:
        router._container_bridge_host = mod._container_bridge_host
    if mod._running_in_container is not router._running_in_container:
        router._running_in_container = mod._running_in_container
    return router.resolve_ollama_base_url(openai_compat=openai_compat)


__all__ = [
    "normalize_ollama_provider",
    "resolve_ollama_base_url",
]
