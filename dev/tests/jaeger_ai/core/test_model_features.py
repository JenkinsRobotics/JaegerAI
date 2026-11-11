"""Unit tests for model feature passport resolution."""
from __future__ import annotations

import pytest

from jaeger_ai.core.models.model_features import (
    WEIGHTS_OPEN,
    WEIGHTS_PROPRIETARY,
    features_dict_for_inventory,
    resolve_model_features,
    validate_effort_for_model,
)


def test_catalog_gpt5_has_effort_and_tools():
    p = resolve_model_features("gpt-5", provider_id="openai")
    assert p.open_weights is False
    assert p.weights_class == WEIGHTS_PROPRIETARY
    assert p.tool_use is True
    assert p.supports_thinking is True
    assert "medium" in p.effort_modes
    assert p.effort_param == "reasoning_effort"


def test_local_qwen_is_open_weights():
    p = resolve_model_features("qwen2.5-coder:7b", provider_id="ollama-local")
    assert p.open_weights is True
    assert p.weights_class == WEIGHTS_OPEN
    assert p.tool_use is True


def test_live_probe_overrides_tools_and_thinking():
    p = resolve_model_features(
        "custom-local",
        provider_id="ollama-local",
        live={
            "capabilities": ["completion", "tools", "thinking"],
            "thinking": {"values": ["low", "high"], "default": "low"},
        },
    )
    assert p.tool_use is True
    assert p.supports_thinking is True
    assert p.effort_modes == ("low", "high")
    assert "live_probe" in p.sources


def test_inventory_dict_shape():
    row = features_dict_for_inventory("claude-sonnet-4-6", provider_id="anthropic")
    assert row["weights_class"] == WEIGHTS_PROPRIETARY
    assert row["tool_use"] is True
    assert isinstance(row["effort_modes"], list)
    assert row["supports_thinking"] is True


def test_validate_effort_rejects_unsupported():
    with pytest.raises(ValueError, match="does not support"):
        validate_effort_for_model("o1-mini", "xhigh", provider_id="openai")
    assert validate_effort_for_model("o1-mini", "high", provider_id="openai") == "high"
    assert validate_effort_for_model("o1-mini", "auto", provider_id="openai") is None
