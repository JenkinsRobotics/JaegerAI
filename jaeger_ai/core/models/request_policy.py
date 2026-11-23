"""Request routing and final-payload policy shared by Gateway model consumers.

Provider adapters still own inference. This module never loads model weights,
executes tools, invents a fallback, or owns conversations.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sys
from typing import Any
from urllib.parse import urlparse

from jaeger_ai.contract.model_ids import split_routed_model_id
from .router import normalize_ollama_provider


class ModelPolicyError(RuntimeError):
    pass


class LocalInferenceBusy(RuntimeError):
    """A temporary host constraint, eligible for an already configured fallback."""


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


def _encoded_image_preview(value: Any) -> bool:
    """Recognize bounded image bytes; an arbitrary string under this key is text."""
    if not isinstance(value, str) or len(value) > 128_000:
        return False
    import base64
    import binascii
    try:
        header = base64.b64decode(value, validate=True)[:12]
    except (ValueError, binascii.Error):
        return False
    return (header.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a"))
            or (header.startswith(b"RIFF") and header[8:12] == b"WEBP"))


def payload_text(payload: Any) -> str:
    """Extract text without copying image bytes into policy logs/classification.

    Skip developer-owned ``system`` (and tool schemas): those routinely mention
    ``~/.ssh``, private keys, or "do not share" as safety instructions, which
    must not classify a public user turn as private.
    """
    if isinstance(payload, str):
        if payload.lstrip().startswith(("{", "[")):
            try:
                return payload_text(json.loads(payload))
            except (ValueError, RecursionError):
                pass
        return "" if payload.startswith("data:image/") else payload
    if isinstance(payload, list):
        return "\n".join(payload_text(item) for item in payload)
    if isinstance(payload, dict):
        # Keep field names: {"password": "short-value"} is private even when
        # the value alone has no recognizable credential prefix.
        return "\n".join(f"{k}: {payload_text(v)}" for k, v in payload.items()
                         if k not in {"images", "image_url", "data", "tools", "tool_choice", "system"}
                         and not (k == "preview_base64" and _encoded_image_preview(v)))
    return ""


def payload_local_only(payload: Any) -> bool:
    """Read an explicit host-owned egress label from structured payloads.

    Content is never inspected for policy keywords.  Producers that handle a
    local-only source attach ``{"_meta": {"local_only": true}}`` (or a
    top-level ``local_only`` boolean) to that source/result.
    """
    if isinstance(payload, list):
        return any(payload_local_only(item) for item in payload)
    if not isinstance(payload, dict):
        return False
    meta = payload.get("_meta")
    if isinstance(meta, dict) and meta.get("local_only") is True:
        return True
    if payload.get("local_only") is True:
        return True
    return any(payload_local_only(value) for key, value in payload.items()
               if key not in {"_meta", "local_only"})


def require_egress(route: ModelRoute, payload: Any, *, local_only: bool = False) -> None:
    if route.local:
        return
    if local_only or payload_local_only(payload):
        raise ModelPolicyError(
            "This request contains local-only content. Select a configured on-device model "
            "or remove the private content. This payload was not sent to the cloud.")


def require_inference_headroom(
    route: ModelRoute, payload: Any, *, local_only: bool, loading: bool = False,
) -> None:
    if not route.local or sys.platform != "darwin":
        return
    from jaeger_ai.core.gateway.webapp.resource_manager import shared
    from jaeger_ai.core.instance.instance import operator_state_root

    provider = normalize_ollama_provider(route.provider)
    manager = shared(operator_state_root)
    blockers = manager.inference_blockers(
        route.model, ollama_endpoint=route.endpoint if provider == "ollama" else "",
        resident=provider == "local" and not loading,
    )
    # On Apple Silicon unified memory, loading an Ollama model routinely shifts
    # kern.memorystatus_vm_pressure_level from 1 (normal) to 2 (warn). When the
    # real ResourceManager reports WARN (2) while the model is resident or >=2 GB
    # remains free (not CRITICAL >= 4), do not hard-abort the local turn.
    if blockers and hasattr(manager, "_host_snapshot"):
        try:
            snap = manager._host_snapshot()
            lvl = snap.get("mem_pressure") or 1
            free_gb = snap.get("mem_free_gb")
            loaded_set = set(snap.get("ollama_loaded") or ())
            norm_name = route.model if ":" in route.model.rsplit("/", 1)[-1] else f"{route.model}:latest"
            is_loaded = (provider == "local" and not loading) or (norm_name in loaded_set) or (route.model in loaded_set)
            if lvl < 4 and (is_loaded or (free_gb is not None and free_gb >= 1.5)):
                blockers = [b for b in blockers if b != "memory pressure is high"]
            if lvl < 4 and (is_loaded or provider == "ollama") and free_gb is not None and free_gb >= 1.5:
                blockers = [b for b in blockers if b != "the model would leave too little memory for the desktop"]
        except Exception:  # noqa: BLE001 — fail safe to original blockers
            pass
    if blockers:
        message = "On-device model paused because " + ", ".join(blockers) + ". Retry when the Mac has more headroom."
        stays_local = local_only or payload_local_only(payload)
        recorder = getattr(manager, "record_inference_deferral", None)
        if callable(recorder):
            recorder(
                route.model,
                blockers,
                outcome="blocked_private" if stays_local else "deferred_fallback_eligible",
            )
        if stays_local:
            raise ModelPolicyError(message)
        raise LocalInferenceBusy(message)


WITHHELD_NOTE = ("[Withheld: this tool output looks local-only (credential, ID or other private "
                 "content), so it was not sent to the cloud model. Say so briefly and continue "
                 "without it; for this content the owner can switch to an on-device model.]")


def _is_tool_message(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get("role") in {"tool", "function"}:
        return True
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") in {"tool_result", "function_call_output"}
        for part in content)


def withhold_private_tool_results(messages: Any) -> tuple[Any, int]:
    """Replace tool outputs that classify as private with a short note.

    A private tool output used to fail the whole turn at the next model call
    (``require_egress``), after the work was done. Withholding just that output
    keeps the boundary (nothing private leaves) and lets the turn finish."""
    if not isinstance(messages, list):
        return messages, 0
    out, withheld = [], 0
    for message in messages:
        if _is_tool_message(message) and payload_local_only(message.get("content")):
            replaced = dict(message)
            content = message.get("content")
            if isinstance(content, list):
                replaced["content"] = [
                    {**part, "content": WITHHELD_NOTE} if isinstance(part, dict)
                    and part.get("type") in {"tool_result", "function_call_output"} else part
                    for part in content]
            else:
                replaced["content"] = WITHHELD_NOTE
            out.append(replaced)
            withheld += 1
        else:
            out.append(message)
    return out, withheld


def withhold_private_result(result: Any) -> Any:
    """Same rule for one tool result returned straight to a cloud CLI model."""
    if payload_local_only(result):
        return {"ok": False, "withheld": True, "error_type": "local_only", "message": WITHHELD_NOTE}
    return result


def select_request_client(config, layout, *, model=None, provider=None, default_client=None, controls=None):
    """Preserve the admitted provider/model pair, including CLI and local lanes."""
    from .external_model import ExternalModelClient
    from .configuration import _BASE_URLS, _CREDENTIALS, _reject_cross_vendor_pair
    lane, name = split_routed_model_id(model or "")
    owner = str(provider or lane or config.external_model.provider).strip().lower()
    owner = {"ollama-local": "ollama", "ollama_cloud": "ollama-cloud", "ollamacloud": "ollama-cloud"}.get(owner, owner)
    _CLI_LANES = {"grok": "grok", "chatgpt": "codex", "codex": "codex", "gemini": "gemini", "agy": "agy", "claude": "claude"}
    selected_lane = owner
    # A bare Gemini/Gemma name (the "Gemini API · AI Studio" picker group) goes to
    # the Gemini API with the AI Studio key; ``agy``/``agy/...`` stay on the CLI lane.
    gemini_api = (owner == "gemini" and bool(name) and "/" not in name
                  and name.startswith(("gemini-", "gemma-")))
    if owner == "gemini" and not gemini_api:
        try:
            from jaeger_ai.features.cli_backends.discovery import preferred_gemini_backend
            _CLI_LANES = {**_CLI_LANES, "gemini": preferred_gemini_backend()}
        except Exception:  # noqa: BLE001
            pass
    if owner in _CLI_LANES and not gemini_api:
        if not name or name in {"default", owner, "chatgpt", "gemini"}:
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
            ensure_local_ollama, ollama_cloud_api_model,
            ollama_cloud_uses_direct_api, resolve_ollama_base_url,
            resolve_ollama_cloud_base_url,
        )
        if ensure_local_ollama():
            # Ollama Desktop can execute signed-in ``:cloud`` models without
            # exposing an API key to Jaeger.  Keep the requested lane for
            # policy/telemetry, but execute through the loopback daemon.
            owner = "ollama"
            ext.base_url = resolve_ollama_base_url()
            ext.api_key_credential = ""
            ext.api_key_env = ""
            name = f"{ollama_cloud_api_model(name)}:cloud"
        elif ollama_cloud_uses_direct_api():
            ext.base_url = resolve_ollama_cloud_base_url(openai_compat=False)
            ext.api_key_credential = ext.api_key_credential or "ollama_cloud_api_key"
            ext.api_key_env = ext.api_key_env or "OLLAMA_API_KEY"
            name = ollama_cloud_api_model(name)
        else:
            raise ModelPolicyError(
                "Ollama Cloud is not connected. Open Ollama and sign in, "
                "or configure an Ollama API key."
            )
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
        # Ollama Cloud counts hidden reasoning and the visible answer or tool
        # call against the same num_predict limit. The local default can run
        # out during reasoning before producing either.
        ext.max_tokens = (4096 if selected_lane == "ollama-cloud"
                          else type(ext).model_fields["max_tokens"].default)
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
    # Per-request lane controls (voice brain: small window, thinking off,
    # short answers). Only known model fields; never credentials or URLs.
    for key, value in (controls or {}).items():
        if key in {"ctx", "reasoning_effort", "max_tokens", "temperature", "first_progress_timeout_s"} and value is not None:
            setattr(ext, key, value)
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
        if not self.route.local and not self.local_only:
            messages, _ = withhold_private_tool_results(messages)
        policy_payload = {"messages": messages}
        require_egress(self.route, policy_payload, local_only=self.local_only)
        formatted = self.adapter.format_messages(messages, tools, system)
        self._formatted_policy = (self._fingerprint(formatted), policy_payload)
        return formatted

    def call(self, formatted, interrupt_event, **kwargs):
        checked = self._formatted_policy
        payload = checked[1] if checked and checked[0] == self._fingerprint(formatted) else formatted
        require_egress(self.route, payload, local_only=self.local_only)
        require_inference_headroom(self.route, payload, local_only=self.local_only)
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
        route = route_for(self.client)
        require_egress(route, messages, local_only=self.local_only)
        require_inference_headroom(route, messages, local_only=self.local_only)
        return self.client.chat(messages, **kwargs)
