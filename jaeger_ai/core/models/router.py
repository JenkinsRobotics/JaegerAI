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

    for host in candidates:
        if _reachable(host, _DEFAULT_OLLAMA_PORT):
            chosen = host
            break

    root = f"http://{chosen}:{_DEFAULT_OLLAMA_PORT}"
    return f"{root}/v1" if openai_compat else root


def normalize_ollama_provider(provider: str) -> str:
    """Normalize user/profile aliases ('ollama-local', 'ollama-cloud') to 'ollama'."""
    name = (provider or "").strip().lower()
    if name in {"ollama-local", "ollama-cloud", "ollama_cloud", "ollamacloud"}:
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

_PATTERNS_PATH = Path(__file__).with_name("sensitivity_patterns.yaml")
_DEFAULT_CLOUD = "glm-5.3-flash:cloud"
_DEFAULT_LOCAL = "gemma-4-26b:latest"

# Built-in fallback sensitivity keywords if YAML is absent
_DEFAULT_PRIVATE_KEYWORDS = [
    "password", "secret", "api_key", "token", "ssn", "credit_card",
    "private_key", "confidential", "internal_only", "classified"
]


@dataclass(frozen=True)
class SensitivityDecision:
    classification: str  # "public" | "private"
    model: str
    provider: str
    reason: str
    tokens_est: int


def _load_rules() -> tuple[list[str], list[re.Pattern[str]]]:
    keywords: list[str] = list(_DEFAULT_PRIVATE_KEYWORDS)
    patterns: list[re.Pattern[str]] = []
    if _PATTERNS_PATH.exists():
        try:
            import yaml  # type: ignore
            raw = yaml.safe_load(_PATTERNS_PATH.read_text(encoding="utf-8")) or {}
            loaded_kw = [str(k).strip().lower() for k in (raw.get("private_keywords") or []) if str(k).strip()]
            if loaded_kw:
                keywords = loaded_kw
            for item in raw.get("private_patterns") or []:
                text = str(item or "").strip()
                if text.startswith("re:"):
                    text = text[3:]
                if text:
                    try:
                        patterns.append(re.compile(text))
                    except re.error:
                        continue
        except Exception:  # noqa: BLE001
            pass
    return keywords, patterns


def estimate_tokens(text: str) -> int:
    """Estimate token count for audit logging (character count heuristic)."""
    body = text or ""
    if not body:
        return 0
    return max(1, (len(body) + 3) // 4)


def classify(text: str) -> tuple[str, str]:
    """Classify user text as 'public' or 'private' and return the classification & reason."""
    body = text or ""
    lowered = body.lower()
    keywords, patterns = _load_rules()
    for kw in keywords:
        if kw in lowered:
            return "private", f"keyword:{kw}"
    for pat in patterns:
        if pat.search(body):
            return "private", f"pattern:{pat.pattern}"
    return "public", "default"


def _log_path() -> Path:
    from jaeger_ai.core.instance.instance import operator_state_root
    root = operator_state_root()
    path = root / "logs" / "sensitivity_gate.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_decision(decision: SensitivityDecision, *, text_preview: str = "") -> Path:
    """Record an audit trail entry for every model routing decision."""
    row = {
        "ts": time.time(),
        "class": decision.classification,
        "model": decision.model,
        "provider": decision.provider,
        "tokens": decision.tokens_est,
        "reason": decision.reason,
        "preview": (text_preview or "")[:160],
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
    return _DEFAULT_LOCAL


def decide(
    text: str,
    *,
    config: Any | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> SensitivityDecision:
    """Decide model target based on privacy classification."""
    classification, reason = classify(text)
    tokens = estimate_tokens(text)
    if classification == "private":
        return SensitivityDecision(
            classification="private",
            model=_local_model(config),
            provider="ollama",
            reason=reason,
            tokens_est=tokens,
        )
    chosen_model = (model or "").strip() or None
    chosen_provider = (provider or "").strip().lower() or None
    if chosen_provider:
        chosen_provider = normalize_ollama_provider(chosen_provider)
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
    log: bool = True,
) -> tuple[str | None, str | None, SensitivityDecision]:
    """Classify input text, enforce local execution for private queries, and log decision."""
    decision = decide(text, config=config, model=model, provider=provider)
    if log:
        log_decision(decision, text_preview=text)
    return decision.model, decision.provider, decision


# ---------------------------------------------------------------------------
# 3. Dynamic Session Model Selection
# ---------------------------------------------------------------------------

def select_client(default: Any, config: Any, layout: Any, model: str | None = None, provider: str | None = None) -> Any:
    """Select or reconfigure an LLM client dynamically for this conversation turn."""
    if not model or model == "default":
        return default

    from jaeger_ai.core.models.configuration import _BASE_URLS, _CREDENTIALS, _reject_cross_vendor_pair
    from jaeger_ai.core.models.external_model import ExternalModelClient

    selected = str(model).strip()
    owner = normalize_ollama_provider(str(provider or "").strip().lower())
    ext = config.external_model.model_copy(deep=True)
    owner = owner or (ext.provider if ext.enabled else "local")
    owner = normalize_ollama_provider(owner)
    current = str(getattr(default, "model_name", "") or "")

    if selected == current and owner == getattr(default, "provider", owner):
        return default

    if owner not in _BASE_URLS or owner == "cli":
        raise ValueError(
            "Per-conversation model selection requires a configured external provider; "
            "local/CLI model changes use instance settings."
        )

    _reject_cross_vendor_pair(owner, selected)

    if owner != ext.provider:
        if owner == "ollama":
            ext.base_url = resolve_ollama_base_url()
            ext.api_key_credential = ""
            ext.api_key_env = ""
        else:
            ext.base_url = _BASE_URLS[owner]
            ext.api_key_credential = _CREDENTIALS.get(owner, "")
            ext.api_key_env = ""
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
    """Privacy and sensitivity governance gate for prompt routing."""

    @staticmethod
    def classify(text: str) -> tuple[str, str]:
        return classify(text)

    @staticmethod
    def decide(
        text: str,
        *,
        config: Any | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> SensitivityDecision:
        return decide(text, config=config, model=model, provider=provider)

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
    "classify",
    "decide",
    "estimate_tokens",
    "log_decision",
    "normalize_ollama_provider",
    "resolve_ollama_base_url",
    "select_client",
]

