"""Unit tests for model provider presets."""

import pytest
from jaeger_ai.core.instance.presets.provider_presets import (
    PROVIDER_PRESETS,
    get_provider_preset,
)


def test_provider_presets_lookup():
    deepseek = get_provider_preset("deepseek")
    assert deepseek["provider"] == "deepseek"
    assert "api.deepseek.com" in deepseek["base_url"]

    groq = get_provider_preset("groq")
    assert groq["provider"] == "groq"
    assert groq["api_key_env"] == "GROQ_API_KEY"


def test_unknown_preset_raises_value_error():
    with pytest.raises(ValueError, match="Unknown provider preset"):
        get_provider_preset("nonexistent")
