"""Request routing and final-payload policy shared by Gateway model consumers.

Provider adapters still own inference. This module never loads model weights,
executes tools, invents a fallback, or owns conversations.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    selected_lane = owner
    # Product Ollama cloud lanes use the configured daemon subscription. A
    # directly configured hosted endpoint remains a distinct explicit route.
    if owner == "ollama-cloud" and config.external_model.provider != "ollama-cloud":
        owner = "ollama"
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
    if owner == "ollama" and not ext.base_url:
        ext.base_url = "http://127.0.0.1:11434/v1"
    ext.enabled, ext.provider, ext.model = True, owner, name
    client = ExternalModelClient(ext, layout)
    client.selected_lane = selected_lane
    return client


class GovernedAdapter:
    """Check every actual call, including accumulated tool results and retries."""
    def __init__(self, adapter, route: ModelRoute, *, local_only=False):
        self.adapter, self.route, self.local_only = adapter, route, local_only

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def call(self, formatted, interrupt_event, **kwargs):
        require_egress(self.route, formatted, local_only=self.local_only)
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
