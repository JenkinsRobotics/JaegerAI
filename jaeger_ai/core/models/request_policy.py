"""Request routing and final-payload policy shared by Gateway model consumers.

Provider adapters still own inference. This module never loads model weights,
executes tools, invents a fallback, or owns conversations.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from jaeger_ai.contract.model_ids import split_routed_model_id
from .router import classify, normalize_ollama_provider


class ModelPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    endpoint: str
    local: bool
    reason: str = "selected"

    def receipt(self):
        return {"provider": self.provider, "model": self.model,
                "location": "device" if self.local else "external", "reason": self.reason}


def route_for(client: Any, *, reason: str = "selected") -> ModelRoute:
    if getattr(client, "kind", None) == "local":
        return ModelRoute("local", str(getattr(client, "model_name", "local")), "", True, reason)
    ext = client.ext
    selected_lane = getattr(client, "selected_lane", ext.provider)
    provider = normalize_ollama_provider(ext.provider)
    endpoint = str(ext.base_url or "")
    # An Ollama daemon can forward :cloud models. Loopback is not enough.
    local = (selected_lane not in {"ollama-cloud", "ollama_cloud", "ollamacloud"}
             and provider in {"ollama", "lmstudio", "vllm"}
             and urlparse(endpoint).hostname in {"127.0.0.1", "localhost", "::1"}
             and not ext.model.endswith((":cloud", "-cloud")))
    return ModelRoute(selected_lane, ext.model, endpoint, local, reason)


def payload_text(payload: Any) -> str:
    """Extract text without copying image bytes into policy logs/classification."""
    if isinstance(payload, str):
        return "" if payload.startswith("data:image/") else payload
    if isinstance(payload, list):
        return "\n".join(payload_text(item) for item in payload)
    if isinstance(payload, dict):
        return "\n".join(payload_text(v) for k, v in payload.items()
                         if k not in {"images", "image_url", "data", "tools", "tool_choice"})
    return ""


def require_egress(route: ModelRoute, payload: Any, *, local_only: bool = False) -> None:
    if route.local:
        return
    private = classify(payload_text(payload))[0] == "private"
    if local_only or private:
        raise ModelPolicyError(
            "This request contains local-only content. Select a configured on-device model "
            "or remove the private content. This payload was not sent to the cloud.")


def select_request_client(config, layout, *, model=None, provider=None, default_client=None):
    """Preserve the admitted provider/model pair, including CLI and local lanes."""
    from .external_model import ExternalModelClient
    from .configuration import _BASE_URLS, _CREDENTIALS, _reject_cross_vendor_pair
    lane, name = split_routed_model_id(model or "")
    owner = str(provider or lane or config.external_model.provider).strip().lower()
    owner = {"ollama-local": "ollama", "ollama_cloud": "ollama-cloud", "ollamacloud": "ollama-cloud"}.get(owner, owner)
    _CLI_LANES = {"grok": "grok", "chatgpt": "codex", "codex": "codex", "gemini": "gemini", "agy": "agy", "claude": "claude"}
    selected_lane = owner
    if owner in _CLI_LANES:
        if not name or name in {"default", owner, "chatgpt"}:
            name = _CLI_LANES[owner]
        elif name.startswith("cli:"):
            name = name.split(":", 1)[1]
        owner = "cli"
    # Ollama Cloud primarily uses the signed-in local Ollama app.
    # The direct ollama.com API is used only when an API key is present.
    if owner in {"huggingface", "hf", "in-process"}:
        owner = "local"
    if not name or name in {"default", "jaeger", "none"}:
        name = config.external_model.model if config.external_model.enabled else "local"
    if name == "local" or owner == "local":
        if callable(default_client):
            local_config = config.model_copy(deep=True)
            local_config.external_model.enabled = False
            if name not in {"local", "default", "unconfigured"}:
                from .configuration import selected_model_config
                local_config, _, _ = selected_model_config(local_config, provider="local", model=name)
            default_client = default_client(local_config)
        if default_client is not None and getattr(default_client, "kind", None) == "local":
            return default_client
        raise ModelPolicyError("The selected on-device engine is not loaded. Configure a local provider in Models.")
    ext = config.external_model.model_copy(deep=True)
    if owner not in _BASE_URLS and owner != config.external_model.provider:
        raise ModelPolicyError(f"Unsupported model provider: {owner}")
    _reject_cross_vendor_pair(owner, name)
    if owner != ext.provider:
        ext.base_url = _BASE_URLS.get(owner, "")
        ext.api_key_credential = _CREDENTIALS.get(owner, "")
        ext.api_key_env = ""
    if owner == "ollama-cloud":
        from jaeger_ai.core.models.router import (
            ensure_local_ollama, ollama_cloud_uses_direct_api, resolve_ollama_cloud_base_url,
        )
        if not ollama_cloud_uses_direct_api() and not ensure_local_ollama():
            raise ModelPolicyError("Starting Ollama… didn't finish. Open the Ollama app and try again.")
        ext.base_url = resolve_ollama_cloud_base_url()
        if ollama_cloud_uses_direct_api():
            ext.api_key_credential = ext.api_key_credential or "ollama_cloud_api_key"
            ext.api_key_env = ext.api_key_env or "OLLAMA_API_KEY"
        else:
            ext.api_key_credential = ""
            ext.api_key_env = ""
    elif owner in {"ollama", "ollama-local"}:
        from jaeger_ai.core.models.router import ensure_local_ollama, resolve_ollama_base_url
        if not ensure_local_ollama():
            raise ModelPolicyError("Starting Ollama… didn't finish. Open the Ollama app and try again.")
        if not ext.base_url:
            ext.base_url = resolve_ollama_base_url()
    if owner != ext.provider or name != ext.model:
        ext.ctx = 0
        # An unrelated provider's output allowance is not this model's
        # configuration. In particular a CLI's 32K setting consumed half
        # a small local window before its first prompt could fit.
        ext.max_tokens = type(ext).model_fields['max_tokens'].default
        ext.reasoning_effort = "auto"
        ext.temperature = ext.top_p = None
        ext.verbosity = ext.thinking_budget_tokens = None
        ext.first_progress_timeout_s = None
        # A declared alternative is also a configured selectable model. Keep
        # its own controls when the user selects it directly, just as on fallback.
        for alternative in config.external_model.fallback:
            if normalize_ollama_provider(alternative.provider) != owner or alternative.model != name:
                continue
            for key in ("ctx", "reasoning_effort", "temperature", "top_p", "verbosity",
                        "thinking_budget_tokens", "first_progress_timeout_s"):
                setattr(ext, key, getattr(alternative, key))
            for key in ("max_tokens", "timeout_s"):
                value = getattr(alternative, key)
                if value is not None:
                    setattr(ext, key, value)
            if alternative.base_url:
                if alternative.base_url != ext.base_url:
                    ext.api_key_credential = _CREDENTIALS.get(owner, "")
                    ext.api_key_env = ""
                ext.base_url = alternative.base_url
            break
    ext.enabled, ext.provider, ext.model = True, owner, name
    client = ExternalModelClient(ext, layout)
    client.selected_lane = selected_lane
    return client


class GovernedAdapter:
    """Check every actual call, including accumulated tool results and retries."""
    def __init__(self, adapter, route: ModelRoute, *, local_only=False):
        self.adapter, self.route, self.local_only = adapter, route, local_only
        self._formatted_policy = None

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    @staticmethod
    def _fingerprint(formatted):
        return hashlib.sha256(json.dumps(formatted, sort_keys=True, default=str).encode()).digest()

    def format_messages(self, messages, tools, system):
        # CLI adapters flatten tool schemas into prose. Classify the actual
        # conversation and system context before that conversion, so a tool's
        # description of private keys is not mistaken for supplied private data.
        policy_text = payload_text({"messages": messages, "system": system})
        require_egress(self.route, policy_text, local_only=self.local_only)
        formatted = self.adapter.format_messages(messages, tools, system)
        self._formatted_policy = (self._fingerprint(formatted), policy_text)
        return formatted

    def call(self, formatted, interrupt_event, **kwargs):
        checked = self._formatted_policy
        payload = checked[1] if checked and checked[0] == self._fingerprint(formatted) else formatted
        require_egress(self.route, payload, local_only=self.local_only)
        return self.adapter.call(formatted, interrupt_event, **kwargs)


def guarded_adapter(adapter, *, local_only=False):
    """Wrap an existing fallback without borrowing the primary model's identity."""
    if isinstance(adapter, GovernedAdapter):
        return adapter
    provider = str(getattr(adapter, "provider", getattr(adapter, "name", "external")))
    model = str(getattr(adapter, "model", getattr(adapter, "backend_id", "unknown")))
    endpoint = str(getattr(adapter, "base_url", "") or "")
    local = (provider in {"ollama", "lmstudio", "vllm"}
             and urlparse(endpoint).hostname in {"127.0.0.1", "localhost", "::1"}
             and not model.endswith((":cloud", "-cloud")))
    return GovernedAdapter(adapter, ModelRoute(provider, model, endpoint, local, "fallback"),
                           local_only=local_only)


class GovernedClient:
    """Apply the same boundary to utility/finalizer calls made through client.chat."""
    def __init__(self, client, *, local_only=False):
        self.client, self.local_only = client, local_only

    def __getattr__(self, name):
        return getattr(self.client, name)

    def chat(self, messages, **kwargs):
        require_egress(route_for(self.client), messages, local_only=self.local_only)
        return self.client.chat(messages, **kwargs)
