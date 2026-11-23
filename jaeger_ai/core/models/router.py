"""Unified Model Routing, Endpoint Discovery, and Privacy Gating.

This module unifies three closely related responsibilities into one cohesive place
that new developers can easily understand:
  1. Endpoint Discovery: Locating the Ollama service across host/container/LAN.
  2. Privacy / Sensitivity Gating: Routing private queries to local models and
     public queries to cloud/external models, maintaining an audit log.
  3. Dynamic Client Selection: Selecting or re-configuring the LLM client per
     conversation turn without modifying permanent instance configurations.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 1. Endpoint Discovery & Normalization (Ollama / Local / Container)
# ---------------------------------------------------------------------------

_DEFAULT_OLLAMA_PORT = 11434
_PROBE_TIMEOUT_S = 0.2


def _normalize_openai_base(url: str) -> str:
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "http://" + text
    if text.endswith("/v1"):
        return text
    return text + "/v1"


def _reachable(host: str, port: int = _DEFAULT_OLLAMA_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False


def _container_bridge_host() -> str:
    try:
        from jaeger_ai.core.runtime.host_environment import snapshot
        host = str((snapshot([]).get("container_host_address") or "")).strip()
        return host or "192.168.64.1"
    except Exception:  # noqa: BLE001
        return "192.168.64.1"


def _running_in_container() -> bool:
    if os.environ.get("JAEGER_IN_CONTAINER", "").strip().lower() in {"1", "true", "yes"}:
        return True
    for marker in ("/.dockerenv", "/run/.containerenv"):
        try:
            if Path(marker).exists():
                return True
        except OSError:
            continue
    return False


def resolve_ollama_base_url(*, openai_compat: bool = True) -> str:
    """Resolve the reachable Ollama base URL across host, container, and LAN.

    Priority:
      1. ``OLLAMA_BASE_URL`` environment override
      2. ``OLLAMA_HOST`` environment override
      3. First reachable candidate between loopback and container bridge IP
      4. Default loopback (http://127.0.0.1:11434)
    """
    env_base = os.environ.get("OLLAMA_BASE_URL", "").strip()
    if env_base:
        return _normalize_openai_base(env_base) if openai_compat else env_base.rstrip("/")

    env_host = os.environ.get("OLLAMA_HOST", "").strip()
    if env_host:
        base = _normalize_openai_base(env_host)
        return base if openai_compat else base.removesuffix("/v1")

    bridge = _container_bridge_host()
    if _running_in_container():
        candidates = [bridge, "127.0.0.1", "localhost"]
        chosen = bridge
    else:
        candidates = ["127.0.0.1", "localhost", bridge]
        chosen = "127.0.0.1"

    PROXY_PORT = 11435  # authenticated container-guest proxy port (no longer shipped)
    chosen_port = _DEFAULT_OLLAMA_PORT if chosen in {"127.0.0.1", "localhost", "::1"} else PROXY_PORT
    for host in candidates:
        # The VM reaches the authenticated bridge, never raw Ollama on the LAN.
        port = _DEFAULT_OLLAMA_PORT if host in {"127.0.0.1", "localhost", "::1"} else PROXY_PORT
        if _reachable(host, port):
            chosen = host
            chosen_port = port
            break

    root = f"http://{chosen}:{chosen_port}"
    return f"{root}/v1" if openai_compat else root


OLLAMA_CLOUD_API = "https://ollama.com/api"
OLLAMA_CLOUD_OPENAI = "https://ollama.com/v1"



def ollama_cloud_api_model(name: str) -> str:
    """Drop the ``:cloud`` / ``-cloud`` suffix the direct API does not accept."""
    raw = (name or "").strip()
    lower = raw.lower()
    if lower.endswith(":cloud"):
        return raw[:-len(":cloud")]
    if lower.endswith("-cloud"):
        return raw[:-len("-cloud")]
    return raw


def ollama_cloud_uses_direct_api() -> bool:
    """True only when ~/.jaeger/secrets.env has an Ollama API key."""
    try:
        from jaeger_ai.core.secrets_env import ollama_api_key
        return bool(ollama_api_key())
    except Exception:
        return False


def ensure_local_ollama(*, timeout_s: float = 25.0) -> bool:
    """Make sure the local Ollama app is listening on :11434.

    If it is down, start it with ``open -a Ollama`` and wait. Emits
    ``Starting Ollama…`` on the live turn stream when a start is needed.
    Returns True when the daemon is reachable.
    """
    import subprocess
    import sys
    import time

    if _reachable("127.0.0.1", _DEFAULT_OLLAMA_PORT) or _reachable("localhost", _DEFAULT_OLLAMA_PORT):
        return True
    try:
        from jaeger_agent import live
        live.emit("turn.progress", {"message": "Starting Ollama…"})
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            subprocess.Popen(
                ["open", "-a", "Ollama"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    while time.monotonic() < deadline:
        if _reachable("127.0.0.1", _DEFAULT_OLLAMA_PORT) or _reachable("localhost", _DEFAULT_OLLAMA_PORT):
            return True
        time.sleep(0.4)
    return False


def resolve_ollama_cloud_base_url(*, openai_compat: bool = True) -> str:
    """Ollama Cloud endpoint: ``https://ollama.com/api`` with a Bearer key.

    The local Ollama app is not used for cloud models. ``openai_compat``
    selects the /v1 alias some OpenAI clients still send; native chat
    uses ``/api/chat`` under ``OLLAMA_CLOUD_API``.
    """
    return OLLAMA_CLOUD_OPENAI if openai_compat else OLLAMA_CLOUD_API


def normalize_ollama_provider(provider: str) -> str:
    """Normalize local aliases to 'ollama'; keep ollama-cloud distinct."""
    name = (provider or "").strip().lower()
    if name in {"ollama-cloud", "ollama_cloud", "ollamacloud"}:
        return "ollama-cloud"
    if name in {"ollama-local", "ollama_local", "ollamalocal"}:
        return "ollama"
    return name


class EndpointResolver:
    """Convenience class for resolving model daemon endpoints."""

    @staticmethod
    def resolve_ollama(*, openai_compat: bool = True) -> str:
        return resolve_ollama_base_url(openai_compat=openai_compat)

    @staticmethod
    def normalize_provider(provider: str) -> str:
        return normalize_ollama_provider(provider)



# ---------------------------------------------------------------------------
# 2. Privacy & Sensitivity Governance Gate
# ---------------------------------------------------------------------------

_DEFAULT_CLOUD = "glm-5.3-flash"


@dataclass(frozen=True)
class SensitivityDecision:
    classification: str  # "public" | "private"
    model: str
    provider: str
    reason: str
    tokens_est: int


def estimate_tokens(text: str) -> int:
    """Estimate token count for audit logging (character count heuristic)."""
    body = text or ""
    if not body:
        return 0
    return max(1, (len(body) + 3) // 4)


def _log_path() -> Path:
    from jaeger_ai.core.instance.instance import operator_state_root
    root = operator_state_root()
    path = root / "logs" / "sensitivity_gate.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_decision(decision: SensitivityDecision, *, text_preview: str = "") -> Path:
    """Record an audit trail entry for every model routing decision."""
    # Classifiers are imperfect. A diagnostic audit must not become a second
    # plaintext conversation store, even for a prompt classified as public.
    preview = f"<redacted:len={len(text_preview or '')}>"

    row = {
        "ts": time.time(),
        "class": decision.classification,
        "model": decision.model,
        "provider": decision.provider,
        "tokens": decision.tokens_est,
        "reason": decision.reason,
        "preview": preview,
    }
    path = _log_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    return path


def _cloud_model(config: Any | None) -> str:
    ext = getattr(config, "external_model", None) if config is not None else None
    if ext is not None and getattr(ext, "enabled", False):
        name = str(getattr(ext, "model", "") or "").strip()
        if name:
            return name
    return _DEFAULT_CLOUD


def _local_model(config: Any | None) -> str:
    if config is not None:
        for entry in getattr(getattr(config, "external_model", None), "fallback", None) or []:
            model = str(getattr(entry, "model", "") or "").strip()
            provider = str(getattr(entry, "provider", "") or "").strip().lower()
            if model and provider in {"ollama", "ollama-local", ""}:
                if not (model.endswith(":cloud") or model.endswith("-cloud")):
                    return model
    return ""


def decide(
    text: str,
    *,
    config: Any | None = None,
    model: str | None = None,
    provider: str | None = None,
    default_client: Any | None = None,
    local_only: bool = False,
) -> SensitivityDecision:
    """Apply an explicit host-owned egress decision.

    Prompt text is data, not policy.  Callers set ``local_only`` from trusted
    session/source provenance or a user-selected privacy control.
    """
    classification = "private" if local_only else "public"
    reason = "provenance:local_only" if local_only else "provenance:standard"
    tokens = estimate_tokens(text)
    if classification == "private":
        # The in-process GGUF/MLX clients already satisfy the local-only
        # boundary. Keep their loaded model instead of inventing an Ollama
        # dependency (which breaks offline/private turns on local installs).
        if getattr(default_client, "kind", None) == "local":
            return SensitivityDecision(
                classification="private", model="local", provider="local",
                reason=reason, tokens_est=tokens,
            )
        local_model = _local_model(config)
        if not local_model:
            from .request_policy import ModelPolicyError
            raise ModelPolicyError("Local-only content requires a configured on-device model; no model was downloaded or selected automatically.")
        return SensitivityDecision(
            classification="private",
            model=local_model,
            provider="ollama",
            reason=reason,
            tokens_est=tokens,
        )
    chosen_model = (model or "").strip() or None
    chosen_provider = (provider or "").strip().lower() or None
    if chosen_provider:
        chosen_provider = normalize_ollama_provider(chosen_provider)
    # Consult standalone Module 01 (jaeger-models ModelCatalog) when provider is unspecified
    if chosen_model and not chosen_provider:
        try:
            from jaeger_models import BUILTIN_PROFILES, ModelCatalog

            if chosen_model in BUILTIN_PROFILES:
                spec = ModelCatalog().resolve(chosen_model)
                if spec.provider and spec.provider != "unknown":
                    chosen_provider = normalize_ollama_provider(spec.provider)
        except ImportError:
            pass
    return SensitivityDecision(
        classification="public",
        model=chosen_model,
        provider=chosen_provider,
        reason=reason,
        tokens_est=tokens,
    )


def apply_sensitivity_routing(
    text: str,
    *,
    config: Any | None = None,
    model: str | None = None,
    provider: str | None = None,
    default_client: Any | None = None,
    log: bool = True,
    local_only: bool = False,
) -> tuple[str | None, str | None, SensitivityDecision]:
    """Enforce the host's explicit egress decision and log it."""
    decision = decide(text, config=config, model=model, provider=provider,
                      default_client=default_client, local_only=local_only)
    if log:
        log_decision(decision, text_preview=text)
    return decision.model, decision.provider, decision


# ---------------------------------------------------------------------------
# 3. Dynamic Session Model Selection
# ---------------------------------------------------------------------------

def _infer_provider_for_model(model_name: str) -> str | None:
    """Infer the hosting provider when a caller only passes a model name."""
    if not model_name:
        return None
    raw = model_name.strip().lower()
    bare = raw.rsplit("/", 1)[-1]
    if bare.endswith((":cloud", "-cloud")):
        return "ollama-cloud"
    if ":" in bare:
        return "ollama"
    if bare.startswith(("gpt-", "o1-", "o3-", "chatgpt-", "text-embedding-")):
        return "openai"
    if bare.startswith("claude"):
        return "anthropic"
    if bare.startswith("gemini"):
        return "gemini"
    if bare.startswith("grok"):
        return "xai"
    return None


def select_client(default: Any, config: Any, layout: Any, model: str | None = None, provider: str | None = None) -> Any:
    """Select or reconfigure an LLM client dynamically for this conversation turn."""
    if not model or model == "default":
        return default

    from jaeger_ai.core.models.configuration import _BASE_URLS, _CREDENTIALS, _reject_cross_vendor_pair
    from jaeger_ai.core.models.external_model import ExternalModelClient

    selected = str(model).strip()
    current = str(getattr(default, "model_name", "") or "")
    if selected.lower() in ("default", "jaeger", "local", "none") or (selected == current and not provider):
        return default

    owner = normalize_ollama_provider(str(provider or "").strip().lower())
    ext = config.external_model.model_copy(deep=True)

    if not owner or owner in ("local", "cli"):
        inferred = _infer_provider_for_model(selected)
        if inferred:
            owner = inferred
        elif ext.enabled and ext.provider:
            owner = ext.provider
        else:
            owner = "local"
    owner = normalize_ollama_provider(owner)

    if selected == current and owner == getattr(default, "provider", owner):
        return default

    if owner not in _BASE_URLS or owner == "cli":
        raise ValueError(
            "Per-conversation model selection requires a configured external provider; "
            "local/CLI model changes use instance settings."
        )

    _reject_cross_vendor_pair(owner, selected)

    if owner != ext.provider or not ext.enabled:
        if owner == "ollama-cloud":
            ext.base_url = resolve_ollama_cloud_base_url(openai_compat=False)
            ext.api_key_credential = _CREDENTIALS.get(owner, "ollama_cloud_api_key")
            ext.api_key_env = "OLLAMA_API_KEY"
            selected = ollama_cloud_api_model(selected)
        elif owner == "ollama":
            ext.base_url = resolve_ollama_base_url()
            ext.api_key_credential = ""
            ext.api_key_env = ""
        else:
            ext.base_url = _BASE_URLS[owner]
            ext.api_key_credential = _CREDENTIALS.get(owner, "")
            ext.api_key_env = ""
    elif owner == "ollama-cloud":
        ext.base_url = resolve_ollama_cloud_base_url(openai_compat=False)
        ext.api_key_credential = ext.api_key_credential or _CREDENTIALS.get(owner, "ollama_cloud_api_key")
        ext.api_key_env = ext.api_key_env or "OLLAMA_API_KEY"
        selected = ollama_cloud_api_model(selected)
    elif owner == "ollama":
        current_base = str(getattr(ext, "base_url", "") or "").strip().lower()
        needs_repair = (
            not current_base
            or "ollama.com" in current_base
            or current_base.startswith("http://127.0.0.1:")
            or current_base.startswith("http://localhost:")
        )
        if needs_repair:
            ext.base_url = resolve_ollama_base_url()
            ext.api_key_credential = ""
            ext.api_key_env = ""

    ext.enabled = True
    ext.provider = owner
    ext.model = selected
    return ExternalModelClient(ext, layout)


# ===========================================================================
# 4. Object-Oriented Interfaces for New Framework Users
# ===========================================================================

class SensitivityGate:
    """Host-owned egress policy gate."""

    @staticmethod
    def decide(
        text: str,
        *,
        config: Any | None = None,
        model: str | None = None,
        provider: str | None = None,
        local_only: bool = False,
    ) -> SensitivityDecision:
        return decide(text, config=config, model=model, provider=provider,
                      local_only=local_only)

    @staticmethod
    def log_decision(decision: SensitivityDecision, *, text_preview: str = "") -> Path:
        return log_decision(decision, text_preview=text_preview)


class ModelRouter:
    """Central router for endpoint resolution, sensitivity gating, and turn routing."""

    @staticmethod
    def resolve_endpoint(*, openai_compat: bool = True) -> str:
        return resolve_ollama_base_url(openai_compat=openai_compat)

    @staticmethod
    def route_turn(
        text: str,
        *,
        config: Any | None = None,
        model: str | None = None,
        provider: str | None = None,
        log: bool = True,
    ) -> tuple[str | None, str | None, SensitivityDecision]:
        return apply_sensitivity_routing(text, config=config, model=model, provider=provider, log=log)

    @staticmethod
    def select_client(default: Any, config: Any, layout: Any, model: str | None = None, provider: str | None = None) -> Any:
        return select_client(default, config, layout, model, provider)


__all__ = [
    "EndpointResolver",
    "ModelRouter",
    "SensitivityDecision",
    "SensitivityGate",
    "apply_sensitivity_routing",
    "decide",
    "estimate_tokens",
    "log_decision",
    "normalize_ollama_provider",
    "resolve_ollama_base_url",
    "select_client",
]
