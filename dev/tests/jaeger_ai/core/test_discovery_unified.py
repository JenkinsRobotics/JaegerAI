"""Unit tests for the unified discovery module and model package exports."""

from __future__ import annotations

import pathlib
import pytest

from jaeger_ai.core.models import (
    DiscoveredModel,
    EndpointResolver,
    ExternalModelClient,
    ModelRouter,
    SensitivityGate,
    discover_all,
    discover_jaeger,
    discover_local_gguf,
    discover_local_gguf_files,
    discover_local_mlx,
    discover_lmstudio,
    discover_ollama,
    scan_paths,
)
from jaeger_ai.core.models.mlx_client import MlxClient, MlxVlmClient


def test_models_package_exports():
    """Verify clean top-level imports from jaeger_ai.core.models."""
    assert ModelRouter is not None
    assert SensitivityGate is not None
    assert EndpointResolver is not None
    assert ExternalModelClient is not None
    assert MlxClient is not None
    assert MlxVlmClient is not None


def test_unified_discovery_surfaces_clean_types():
    """Verify discovery return types are robust and non-raising."""
    paths = scan_paths()
    assert isinstance(paths, list)

    local_ggufs = discover_local_gguf_files()
    assert isinstance(local_ggufs, list)
    for m in local_ggufs:
        assert isinstance(m, DiscoveredModel)
        assert isinstance(m.path, pathlib.Path)
        assert isinstance(m.size_gb, (int, float))

    all_models = discover_all()
    assert "jaeger" in all_models
    assert "local_gguf" in all_models
    assert "local_mlx" in all_models
    assert "ollama" in all_models
    assert "lmstudio" in all_models


def test_mlx_vlm_client_unified_class():
    """Verify MlxVlmClient has correct attribute metadata."""
    assert MlxVlmClient.kind == "local"
    assert MlxVlmClient.is_vlm is True
