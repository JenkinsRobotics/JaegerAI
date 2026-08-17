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


__all__ = ["configure_model"]
