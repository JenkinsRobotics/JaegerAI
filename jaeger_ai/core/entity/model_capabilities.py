"""Certified model/provider roles. Uncertified models are not assigned ReAct."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("jaeger.entity.model_capabilities")

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

ROLES = ("chat", "react", "planning", "critic", "reflection", "vision")

# Live-validated seed. Operator files overlay this.
DEFAULT_CAPABILITIES: dict[str, dict[str, str]] = {
    "kimi-k2.7-code:cloud": {
        "chat": PASS, "react": PASS, "planning": PASS, "critic": PASS, "reflection": PASS, "vision": PASS,
    },
    "glm-5.3-flash:cloud": {
        "chat": PASS, "react": FAIL, "planning": UNKNOWN, "critic": UNKNOWN,
    },
    "gemma-4-26b:latest": {
        "chat": UNKNOWN, "react": UNKNOWN,
    },
}


def _load_overlay(state_root: Path | None) -> dict[str, dict[str, str]]:
    if state_root is None:
        return {}
    path = Path(state_root) / "model_capabilities.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug("capability overlay unreadable: %s", exc)
        return {}


def capabilities_for(model: str, state_root: Path | None = None) -> dict[str, str]:
    overlay = _load_overlay(state_root)
    merged = dict(DEFAULT_CAPABILITIES.get(model) or {})
    extra = overlay.get(model) if isinstance(overlay.get(model), dict) else {}
    merged.update({str(k): str(v).lower() for k, v in extra.items()})
    return merged


def role_status(model: str, role: str, state_root: Path | None = None) -> str:
    caps = capabilities_for(model, state_root)
    return str(caps.get(role) or UNKNOWN).lower()


def is_certified(model: str, role: str, state_root: Path | None = None) -> bool:
    return role_status(model, role, state_root) == PASS


def load_capabilities(state_root: Path | None = None) -> dict[str, dict[str, str]]:
    merged = {k: dict(v) for k, v in DEFAULT_CAPABILITIES.items()}
    overlay = _load_overlay(state_root)
    for model, caps in overlay.items():
        if not isinstance(caps, dict):
            continue
        bucket = merged.setdefault(str(model), {})
        bucket.update({str(k): str(v).lower() for k, v in caps.items()})
    return merged


def certified_for(role: str, caps: dict[str, dict[str, str]] | None = None) -> str | None:
    table = caps if caps is not None else load_capabilities()
    for model, roles in table.items():
        if str(roles.get(role) or "").lower() == PASS:
            return model
    return None


def current_model_name(client: Any) -> str:
    ext = getattr(client, "ext", None)
    if ext is not None:
        return str(getattr(ext, "model", "") or "")
    return str(getattr(client, "model_name", "") or "")


def ensure_role_client(client: Any, role: str, state_root: Path | None = None) -> Any:
    """If the bound client is certified FAIL for ``role``, switch to a PASS fallback.

    Forced via JAEGER_FORCE_MODEL=1.
    """
    import os
    if os.environ.get("JAEGER_FORCE_MODEL", "").strip() in {"1", "true", "yes"}:
        return client
    model = current_model_name(client)
    if not model:
        return client
    status = role_status(model, role, state_root)
    if status != FAIL:
        return client
    # A live Ollama listing is an operator-selected model. Certification
    # governs the production *default*, not an explicit picker choice.
    try:
        from jaeger_ai.core.models.discovery import discover_ollama
        listed = {
            str((row or {}).get("name") or "")
            for row in (discover_ollama().get("models") or [])
        }
        if model in listed:
            logger.info("Keeping operator-selected live model %s for %s", model, role)
            return client
    except Exception:
        pass
    logger.warning("Provider %s is certified %s for %s — routing away", model, status, role)
    try:
        from jaeger_ai.core.entity.events import EventType, JaegerEvent
        from jaeger_ai.core.entity.runtime import EntityRuntime
        EntityRuntime.get_singleton().event_store.append(
            JaegerEvent.typed(
                EventType.PROVIDER_REJECTED.value,
                {"model": model, "role": role, "status": status},
                actor="system:router",
                source="model_capabilities",
            )
        )
    except Exception:
        pass
    # Prefer a known PASS model on the same ollama endpoint.
    for candidate, caps in DEFAULT_CAPABILITIES.items():
        if caps.get(role) == PASS and candidate != model:
            try:
                from jaeger_ai.core.models.router import select_client
                from jaeger_ai.main import _pipeline
                switched = select_client(
                    client,
                    _pipeline.get("config"),
                    _pipeline.get("layout"),
                    model=candidate,
                    provider="ollama",
                )
                logger.info("Routed %s work %s → %s", role, model, candidate)
                try:
                    from jaeger_ai.core.entity.events import EventType, JaegerEvent
                    from jaeger_ai.core.entity.runtime import EntityRuntime
                    EntityRuntime.get_singleton().event_store.append(
                        JaegerEvent.typed(
                            EventType.PROVIDER_SELECTED.value,
                            {"model": candidate, "role": role, "replaced": model},
                            actor="system:router",
                            source="model_capabilities",
                        )
                    )
                except Exception:
                    pass
                return switched
            except Exception as exc:
                logger.debug("Could not switch to %s: %s", candidate, exc)
    return client
