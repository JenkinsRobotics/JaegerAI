"""Backward-compatibility shim for local model discovery.

Unified under `jaeger_ai.core.models.discovery`.
"""

from __future__ import annotations

import sys
from jaeger_ai.core.models import discovery as _mod

_in_tree_models_path = _mod._in_tree_models_path
_operator_state_models_path = _mod._operator_state_models_path
_safe_size_gb = _mod._safe_size_gb
_iter_gguf_files = _mod._iter_gguf_files
_env_override_paths = _mod._env_override_paths
_DEFAULT_SCAN_PATHS = _mod._DEFAULT_SCAN_PATHS
DiscoveredModel = _mod.DiscoveredModel


def scan_paths():
    mod = sys.modules[__name__]
    if mod._in_tree_models_path is not _mod._in_tree_models_path:
        _mod._in_tree_models_path = mod._in_tree_models_path
    if mod._operator_state_models_path is not _mod._operator_state_models_path:
        _mod._operator_state_models_path = mod._operator_state_models_path
    return _mod.scan_paths()


def discover_local_gguf_files():
    mod = sys.modules[__name__]
    if mod._in_tree_models_path is not _mod._in_tree_models_path:
        _mod._in_tree_models_path = mod._in_tree_models_path
    if mod._operator_state_models_path is not _mod._operator_state_models_path:
        _mod._operator_state_models_path = mod._operator_state_models_path
    return _mod.discover_local_gguf_files()


def match_to_registry(discovered):
    return _mod.match_to_registry(discovered)


def discover_local_ollama_models(base_url: str = "http://localhost:11434"):
    return _mod.discover_local_ollama_models(base_url)


__all__ = [
    "DiscoveredModel",
    "discover_local_gguf_files",
    "discover_local_ollama_models",
    "match_to_registry",
    "scan_paths",
]
