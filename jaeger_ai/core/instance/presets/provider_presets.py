"""Model provider presets for JaegerAI (DeepSeek, Groq, OpenRouter, Ollama, LM Studio, local GGUF/MLX)."""

from __future__ import annotations

from typing import Any, Dict

PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 8192,
        "temperature": 0.0,
    },
    "groq": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "max_tokens": 4096,
        "temperature": 0.0,
    },
    "openrouter": {
        "provider": "openrouter",
        "model": "anthropic/claude-3.5-sonnet",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "max_tokens": 4096,
        "temperature": 0.0,
    },
    "ollama": {
        "provider": "ollama",
        "model": "qwen2.5-coder:32b",
        "base_url": "http://localhost:11434/v1",
        "api_key_env": "OLLAMA_API_KEY",
        "max_tokens": 4096,
        "temperature": 0.0,
    },
    "lmstudio": {
        "provider": "lmstudio",
        "model": "local-model",
        "base_url": "http://localhost:1234/v1",
        "api_key_env": "OPENAI_API_KEY",
        "max_tokens": 4096,
        "temperature": 0.0,
    },
}


def get_provider_preset(name: str) -> Dict[str, Any]:
    """Retrieve model provider configuration dictionary by name."""
    preset = PROVIDER_PRESETS.get(name.lower().strip())
    if not preset:
        raise ValueError(f"Unknown provider preset '{name}'. Available: {list(PROVIDER_PRESETS.keys())}")
    return dict(preset)


__all__ = ["PROVIDER_PRESETS", "get_provider_preset"]
