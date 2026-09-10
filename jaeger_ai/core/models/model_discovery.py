"""Backward-compatibility shim for model discovery.

Unified under `jaeger_ai.core.models.discovery`.
"""

from __future__ import annotations

import sys
from jaeger_ai.core.models import discovery as _mod

OLLAMA_URL = _mod.OLLAMA_URL
LMSTUDIO_URL = _mod.LMSTUDIO_URL
OLLAMA_CLOUD_URL = _mod.OLLAMA_CLOUD_URL
_PROBE_TIMEOUT = _mod._PROBE_TIMEOUT
_CLOUD_TIMEOUT = _mod._CLOUD_TIMEOUT
_LMSTUDIO_DIRS = _mod._LMSTUDIO_DIRS
_get_json = _mod._get_json

OLLAMA_CLOUD_CURATED = _mod.OLLAMA_CLOUD_CURATED
OPENAI_CURATED = _mod.OPENAI_CURATED
ANTHROPIC_CURATED = _mod.ANTHROPIC_CURATED
GEMINI_CURATED = _mod.GEMINI_CURATED
XAI_CURATED = _mod.XAI_CURATED


def discover_jaeger():
    return _mod.discover_jaeger()


def discover_local_gguf():
    return _mod.discover_local_gguf()


def discover_local_mlx():
    return _mod.discover_local_mlx()


def discover_ollama_disk():
    return _mod.discover_ollama_disk()


def discover_ollama(base: str | None = None):
    mod = sys.modules[__name__]
    if mod._get_json is not _mod._get_json:
        _mod._get_json = mod._get_json
    return _mod.discover_ollama(base=base)


def discover_lmstudio(base: str = _mod.LMSTUDIO_URL):
    mod = sys.modules[__name__]
    if mod._get_json is not _mod._get_json:
        _mod._get_json = mod._get_json
    return _mod.discover_lmstudio(base=base)


def discover_ollama_cloud(api_key: str = ""):
    return _mod.discover_ollama_cloud(api_key=api_key)


def discover_all(ollama_cloud_key: str = ""):
    mod = sys.modules[__name__]
    if mod._get_json is not _mod._get_json:
        _mod._get_json = mod._get_json
    return _mod.discover_all(ollama_cloud_key=ollama_cloud_key)


__all__ = [
    "discover_all",
    "discover_jaeger",
    "discover_lmstudio",
    "discover_local_gguf",
    "discover_local_mlx",
    "discover_ollama",
    "discover_ollama_cloud",
    "discover_ollama_disk",
    "OLLAMA_CLOUD_CURATED",
    "OPENAI_CURATED",
    "ANTHROPIC_CURATED",
    "GEMINI_CURATED",
    "XAI_CURATED",
]
