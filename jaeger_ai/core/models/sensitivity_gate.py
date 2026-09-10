"""Classify each request public→cloud or private→local before any cloud call.

Stub classifier: config-driven keyword/pattern list in
``sensitivity_patterns.yaml``. No ML. Every decision is appended as JSONL
under ``$JAEGER_STATE_DIR`` / ``~/.jaeger/logs/sensitivity_gate.jsonl`` for
a future usage tracker.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PATTERNS_PATH = Path(__file__).with_name("sensitivity_patterns.yaml")
_DEFAULT_CLOUD = "glm-5.3-flash:cloud"
_DEFAULT_LOCAL = "gemma-4-26b:latest"


@dataclass(frozen=True)
class SensitivityDecision:
    classification: str  # "public" | "private"
    model: str
    provider: str
    reason: str
    tokens_est: int


def _load_rules() -> tuple[list[str], list[re.Pattern[str]]]:
    keywords: list[str] = []
    patterns: list[re.Pattern[str]] = []
    try:
        import yaml  # type: ignore
        raw = yaml.safe_load(_PATTERNS_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — fail-open to empty rules
        return keywords, patterns
    for item in raw.get("private_keywords") or []:
        text = str(item or "").strip().lower()
        if text:
            keywords.append(text)
    for item in raw.get("private_patterns") or []:
        text = str(item or "").strip()
        if text.startswith("re:"):
            text = text[3:]
        if not text:
            continue
        try:
            patterns.append(re.compile(text))
        except re.error:
            continue
    return keywords, patterns


def estimate_tokens(text: str) -> int:
    """Rough token estimate for the decision log (not billed usage)."""
    body = text or ""
    if not body:
        return 0
    return max(1, (len(body) + 3) // 4)


def classify(text: str) -> tuple[str, str]:
    """Return ``(classification, reason)`` — ``public`` or ``private``."""
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
        # Prefer an on-device Ollama tag over a GGUF path for the gate.
    return _DEFAULT_LOCAL


def decide(
    text: str,
    *,
    config: Any | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> SensitivityDecision:
    """Classify and pick provider/model for this request."""
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
    # public → cloud (keep explicit selection when already cloud-capable)
    chosen_model = (model or "").strip() or _cloud_model(config)
    chosen_provider = (provider or "").strip().lower() or "ollama"
    from jaeger_ai.core.models.ollama_endpoint import normalize_ollama_provider
    chosen_provider = normalize_ollama_provider(chosen_provider) or "ollama"
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
    """Return ``(model, provider, decision)`` after the gate runs.

    Always runs before any cloud call on the model-routing path. Private
    requests force the local Ollama tag; public requests keep / default to
    the configured cloud brain.
    """
    decision = decide(text, config=config, model=model, provider=provider)
    if log:
        log_decision(decision, text_preview=text)
    return decision.model, decision.provider, decision


__all__ = [
    "SensitivityDecision",
    "apply_sensitivity_routing",
    "classify",
    "decide",
    "estimate_tokens",
    "log_decision",
]
