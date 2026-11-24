"""Canonical ModelProfile catalog (pydantic-ai + goose + aider patterns)."""

from __future__ import annotations

from dataclasses import replace

from jaeger_contracts import ModelProfile

BUILTIN_PROFILES: dict[str, ModelProfile] = {
    "local/mlx-qwen3-coder": ModelProfile(
        model_id="local/mlx-qwen3-coder",
        provider="mlx",
        context_window=65_536,
        max_output_tokens=8_192,
        supports_native_tools=True,
        supports_structured_output=True,
        supports_prompt_caching=True,
        supports_reasoning=False,
        local_only=True,
    ),
    "local/llama-cpp": ModelProfile(
        model_id="local/llama-cpp",
        provider="llama_cpp",
        context_window=32_768,
        max_output_tokens=4_096,
        supports_native_tools=True,
        supports_structured_output=True,
        supports_prompt_caching=False,
        supports_reasoning=False,
        local_only=True,
    ),
    "anthropic/claude-sonnet": ModelProfile(
        model_id="anthropic/claude-sonnet",
        provider="anthropic",
        context_window=200_000,
        max_output_tokens=16_384,
        supports_native_tools=True,
        supports_structured_output=True,
        supports_prompt_caching=True,
        supports_reasoning=True,
        local_only=False,
    ),
    "openai/gpt-5": ModelProfile(
        model_id="openai/gpt-5",
        provider="openai",
        context_window=400_000,
        max_output_tokens=32_768,
        supports_native_tools=True,
        supports_structured_output=True,
        supports_prompt_caching=True,
        supports_reasoning=True,
        local_only=False,
    ),
    "google/gemini-pro": ModelProfile(
        model_id="google/gemini-pro",
        provider="google",
        context_window=1_000_000,
        max_output_tokens=65_536,
        supports_native_tools=True,
        supports_structured_output=True,
        supports_prompt_caching=True,
        supports_reasoning=True,
        local_only=False,
    ),
}


class ModelCatalog:
    """Offline-first declarative ModelProfile catalog with runtime overrides."""

    def __init__(self, initial: dict[str, ModelProfile] | None = None) -> None:
        self._profiles: dict[str, ModelProfile] = dict(BUILTIN_PROFILES)
        if initial:
            self._profiles.update(initial)

    def register(self, profile: ModelProfile) -> None:
        self._profiles[profile.model_id] = profile

    def resolve(self, model_id: str) -> ModelProfile:
        if model_id in self._profiles:
            return self._profiles[model_id]
        # Prefix/bare-name normalization (crewAI / aider pattern)
        lowered = model_id.strip().lower()
        for key, prof in self._profiles.items():
            if key.lower() == lowered or key.split("/")[-1].lower() == lowered:
                return replace(prof, model_id=model_id)
        is_local = lowered.startswith(("local/", "mlx/", "ollama/", "llama"))
        provider = lowered.split("/", 1)[0] if "/" in lowered else ("local" if is_local else "openai_compat")
        return ModelProfile(
            model_id=model_id,
            provider=provider,
            context_window=32_768,
            local_only=is_local,
        )

    def structured_output_mode(self, model_id: str) -> str:
        """Select optimal structured-output strategy from ModelProfile (pydantic-ai pattern)."""
        p = self.resolve(model_id)
        if p.supports_structured_output:
            return "native"
        if p.supports_native_tools:
            return "tool"
        return "prompted"
