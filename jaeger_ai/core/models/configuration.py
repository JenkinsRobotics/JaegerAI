"""Validated model selection owned by the Jaeger runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml


_BASE_URLS = {
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "ollama-cloud": "https://ollama.com/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "xai": "https://api.x.ai/v1",
}
_CREDENTIALS = {
    "ollama-cloud": "ollama_cloud_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
    "xai": "xai_api_key",
}


def _local_model(model: str) -> tuple[str, str]:
    from jaeger_ai.core.models.model_discovery import discover_local_gguf, discover_local_mlx

    for row in discover_local_gguf():
        if model in {row.get("name"), str(row.get("name") or "").removesuffix(".gguf"), row.get("path")}:
            return str(row["path"]), "llama_cpp_python"
    for row in discover_local_mlx():
        if model in {row.get("name"), row.get("path")}:
            return str(row["path"]), "mlx_lm"
    path = Path(model).expanduser()
    if path.exists():
        if path.is_dir() and ((path / "config.json").exists() or any(path.glob("*.safetensors"))):
            return str(path.resolve()), "mlx_lm"
        if path.suffix.lower() == ".gguf" or (path.is_dir() and any(path.glob("*.gguf"))):
            return str(path.resolve()), "llama_cpp_python"
    raise ValueError(f"Jaeger could not resolve local model {model!r}")


# Providers that serve exactly one vendor's models. A single-vendor API can
# never answer for a different vendor's model, so pairing them is always a
# configuration error rather than a preference. Multi-vendor hosts
# (ollama, ollama-cloud, lmstudio, local, custom endpoints) are deliberately
# absent: ollama-cloud legitimately serves gpt-oss, deepseek, qwen, gemma and
# more, so no vendor inference is valid there.
_SINGLE_VENDOR_PROVIDERS = {"openai", "anthropic", "gemini", "xai"}
# Prefix → the one provider that can serve it. Kept deliberately small and
# unambiguous; anything not listed is simply not checked.
_MODEL_VENDOR_PREFIXES = (
    ("claude", "anthropic"),
    ("gemini", "gemini"),
    ("grok", "xai"),
)


def _reject_cross_vendor_pair(provider: str, model: str) -> None:
    """Refuse a provider/model pair that cannot possibly work.

    A real instance was found configured with provider ``anthropic`` and model
    ``gpt-5.4-mini`` pointed at ``https://api.anthropic.com`` — an OpenAI model
    name sent to Anthropic's endpoint. Nothing validated the pair, so the
    mismatch persisted silently and every turn failed or silently fell back to
    the in-process local model, which reads to the operator as "the model
    picker doesn't work".

    Only obvious cross-vendor pairs are rejected. Multi-vendor hosts are never
    second-guessed, so ``ollama-cloud`` + ``gpt-oss:120b`` stays valid.
    """
    if provider not in _SINGLE_VENDOR_PROVIDERS:
        return
    bare = model.strip().lower().rsplit("/", 1)[-1]
    for prefix, owner in _MODEL_VENDOR_PREFIXES:
        if bare.startswith(prefix) and owner != provider:
            raise ValueError(
                f"provider {provider!r} cannot serve model {model!r} "
                f"({prefix}* models are served by {owner!r}). "
                "Pick a model this provider offers, or switch provider."
            )
    # ``gpt`` needs its own arm: gpt-oss is an open-weights family that
    # multi-vendor hosts legitimately serve, so it only indicts a pairing when
    # the provider is a different single-vendor API.
    if bare.startswith("gpt") and not bare.startswith("gpt-oss") and provider != "openai":
        raise ValueError(
            f"provider {provider!r} cannot serve model {model!r} "
            "(gpt* models are served by 'openai'). "
            "Pick a model this provider offers, or switch provider."
        )


def configure_model(
    layout: Any,
    *,
    provider: Any,
    model: Any,
    base_url: Any = None,
    context_length: Any = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    selected_provider = str(provider or "").strip().lower()
    selected_model = str(model or "").strip()
    if not selected_model:
        raise ValueError("model is required")
    if selected_provider in {"huggingface", "hf", "in-process"}:
        selected_provider = "local"
    if selected_provider not in {"local", *_BASE_URLS}:
        raise ValueError(f"unsupported Jaeger provider: {selected_provider!r}")

    current = load_yaml(layout.config_path, Config)
    updated = current.model_copy(deep=True)
    if selected_provider == "local":
        path, backend = _local_model(selected_model)
        updated.external_model.enabled = False
        updated.model.model_path = path
        updated.model.backend = backend
        if context_length:
            updated.model.ctx = int(context_length)
    else:
        # Validate the PAIR, not each half. provider and model are only
        # meaningful together — an endpoint and a model name that disagree is
        # a broken runtime, not a preference.
        _reject_cross_vendor_pair(selected_provider, selected_model)
        updated.external_model.enabled = True
        updated.external_model.provider = selected_provider
        updated.external_model.model = selected_model
        updated.external_model.base_url = str(base_url or _BASE_URLS[selected_provider]).strip()
        updated.external_model.api_key_credential = _CREDENTIALS.get(selected_provider, "")
        updated.external_model.api_key_env = ""
        if context_length:
            updated.external_model.ctx = int(context_length)

    validated = Config.model_validate(updated.model_dump())
    changed = validated != current
    if changed and not dry_run:
        dump_yaml(layout.config_path, validated)
    return {
        "ok": True,
        "owner": "jaeger",
        "provider": selected_provider,
        "model": selected_model,
        "changed": changed,
        "restart_required": changed,
        "dry_run": bool(dry_run),
    }


def configure_fallback_chain(
    layout: Any,
    entries: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Persist an ordered fallback chain. Empty list clears it."""
    from jaeger_ai.core.instance.schemas import FallbackModel

    if entries is None:
        rows: list[dict[str, Any]] = []
    elif isinstance(entries, list):
        rows = list(entries)
    else:
        raise ValueError("fallback chain must be a list of {provider, model}")

    current = load_yaml(layout.config_path, Config)
    cleaned: list[dict[str, str]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("each fallback entry must be an object")
        provider = str(raw.get("provider") or "").strip().lower()
        model = str(raw.get("model") or "").strip()
        if not provider or not model:
            raise ValueError("each fallback entry needs provider and model")
        if provider == "local":
            raise ValueError(
                "local fallback is disabled — a selected cloud brain must "
                "not load on-device weights"
            )
        _reject_cross_vendor_pair(provider, model)
        FallbackModel.model_validate({
            "provider": provider,
            "model": model,
            "base_url": str(raw.get("base_url") or ""),
        })
        if provider not in {"local", *_BASE_URLS}:
            raise ValueError(f"unsupported Jaeger provider: {provider!r}")
        cleaned.append({
            "provider": provider,
            "model": model,
            "base_url": str(raw.get("base_url") or ""),
        })

    updated = current.model_copy(deep=True)
    updated.external_model.fallback = [
        FallbackModel.model_validate(row) for row in cleaned
    ]
    validated = Config.model_validate(updated.model_dump())
    changed = validated != current
    if changed and not dry_run:
        dump_yaml(layout.config_path, validated)
    return {
        "ok": True,
        "owner": "jaeger",
        "fallback": cleaned,
        "changed": changed,
        "restart_required": changed,
        "dry_run": bool(dry_run),
    }


def dead_brain_reason(reason: str) -> bool:
    """True when the primary cannot serve at all (walk the chain).

    Timeouts, rate limits, and context-length errors stay on the same
    brain — they are request failures, not a dead endpoint.
    """
    lower = (reason or "").lower()
    if not lower:
        return False
    if "429" in lower or "rate limit" in lower:
        return False
    if "context" in lower and ("length" in lower or "window" in lower):
        return False
    if "timeout" in lower or "timed out" in lower:
        return False
    markers = (
        "unreachable", "not configured", "connection", "connect",
        "refused", "401", "403", "dns", "name or service", "api key",
        "needs an api key", "failed to establish", "nodename",
    )
    return any(m in lower for m in markers)


__all__ = ["configure_model", "configure_fallback_chain", "dead_brain_reason"]
