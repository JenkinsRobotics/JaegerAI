"""Canonical runtime inventories for frameworks, models, and capabilities.

WebUI, Gateway, and cognition consume this module. They do not keep a second
catalog. Code support is not the same as configured, reachable, or certified.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from jaeger_ai.contract.frameworks import (
    FRAMEWORKS,
    PRODUCT_DEFAULT_PROFILE,
    PRODUCT_DEFAULT_RUNTIME,
    display_name,
)


def _instance_root() -> Path | None:
    try:
        from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
        return InstanceLayout(root=resolve_instance_dir()).root
    except Exception:
        return None


def framework_inventory(*, probe: Any | None = None) -> list[dict[str, Any]]:
    """Runtime-owned framework rows for the WebUI selector."""
    rows: list[dict[str, Any]] = []
    health: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    if probe is None:
        try:
            from jaeger_ai.features.webui.adapter.profile_catalog import native_ready
            from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
            probe = lambda name, _ready=native_ready, _bridge=jaeger_bridge: _ready(name, _bridge())
        except Exception:
            probe = None
    for f in FRAMEWORKS:
        available = False
        reason = "probe unavailable"
        if f.composes:
            missing = []
            for member in f.composes:
                ok = health.get(member)
                if ok is None and callable(probe):
                    try:
                        ok = bool(probe(member))
                    except Exception as exc:
                        ok = False
                        reasons[member] = type(exc).__name__
                    health[member] = bool(ok)
                if not ok:
                    missing.append(display_name(member))
            available = not missing
            reason = "Ready" if available else ("Unavailable: " + ", ".join(missing))
        else:
            if callable(probe):
                try:
                    available = bool(probe(f.runtime))
                    reason = "Ready" if available else "Unavailable"
                except Exception as exc:
                    available = False
                    reason = type(exc).__name__
            health[f.runtime] = available
            reasons[f.runtime] = reason
        rows.append({
            "runtime_id": f.runtime,
            "profile": f.profile,
            "display_name": f.display_name,
            "agent_id": f.agent_id,
            "available": available,
            "healthy": available,
            "reason": reason,
            "owns_sessions": f.owns_sessions,
            "is_product_default": f.runtime == PRODUCT_DEFAULT_RUNTIME,
            "capabilities": {"turn": bool(f.turn), "composes": list(f.composes)},
        })
    return rows


def _certifications_for(model: str, instance_root: Path | None) -> dict[str, str]:
    try:
        from jaeger_ai.core.instance.provider_certification import load_matrix
        matrix = load_matrix(instance_root) if instance_root is not None else load_matrix(_instance_root() or Path("."))
        out: dict[str, str] = {}
        for role in ("CHAT", "REACT", "PLANNER", "CRITIC", "REFLECTION", "VISION"):
            found = matrix.result_for(model, role)
            if found is None:
                continue
            out[role] = "PASS" if found.passed else "FAIL"
        if out:
            return out
    except Exception:
        pass
    try:
        from jaeger_ai.core.entity.model_capabilities import capabilities_for, ROLES
        caps = capabilities_for(model, (instance_root / "memory") if instance_root else None)
        mapping = {
            "chat": "CHAT", "react": "REACT", "planning": "PLANNER",
            "critic": "CRITIC", "reflection": "REFLECTION", "vision": "VISION",
        }
        return {
            mapping[role]: str(caps[role]).upper()
            for role in ROLES
            if role in caps and role in mapping
        }
    except Exception:
        return {}


def _active_model(instance_root: Path | None) -> dict[str, str]:
    try:
        from jaeger_ai.core.instance.provider_certification import load_matrix, select_production_model
        root = instance_root or _instance_root()
        if root is None:
            return {"provider": "", "model": ""}
        provider, model = select_production_model(load_matrix(root))
        return {"provider": provider, "model": model}
    except Exception:
        return {"provider": "", "model": ""}


def provider_model_inventory(instance_root: Path | None = None) -> dict[str, Any]:
    """Discovered, reachable Ollama (and siblings) plus certification overlay."""
    root = instance_root or _instance_root()
    from jaeger_ai.core.models.discovery import discover_ollama, discover_lmstudio

    ollama = discover_ollama()
    lmstudio = discover_lmstudio()
    providers: list[dict[str, Any]] = []

    def _models(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            name = str(row.get("name") or row.get("id") or "").strip()
            if not name:
                continue
            certs = _certifications_for(name, root)
            react = str(certs.get("REACT") or "").upper()
            out.append({
                "id": name,
                "available": True,
                "usable_for_react": react == "PASS",
                "certifications": certs,
                "capabilities": list(row.get("capabilities") or []),
                "remote_host": row.get("remote_host"),
            })
        return out

    ollama_models = _models(list(ollama.get("models") or []))
    providers.append({
        "id": "ollama",
        "display_name": "Ollama",
        "location": "local_or_cloud",
        "supported": True,
        "configured": True,
        "reachable": bool(ollama.get("online")),
        "reason": None if ollama.get("online") else str(ollama.get("detail") or "offline"),
        "models": ollama_models,
    })
    lm_models = _models(list(lmstudio.get("models") or []))
    providers.append({
        "id": "lmstudio",
        "display_name": "LM Studio",
        "location": "local",
        "supported": True,
        "configured": True,
        "reachable": bool(lmstudio.get("online")),
        "reason": None if lmstudio.get("online") else str(lmstudio.get("detail") or "offline"),
        "models": lm_models,
    })
    for family in ("openai", "anthropic", "gemini", "xai", "openrouter", "groq", "deepseek"):
        providers.append({
            "id": family,
            "display_name": family.replace("_", " ").title(),
            "location": "cloud",
            "supported": True,
            "configured": False,
            "reachable": False,
            "reason": "not configured on this instance",
            "models": [],
        })
    active = _active_model(root)
    return {
        "providers": providers,
        "active": active,
        "product_default_runtime": PRODUCT_DEFAULT_RUNTIME,
        "generated_at": time.time(),
    }


def webui_model_catalog(instance_root: Path | None = None) -> dict[str, Any]:
    """Shape expected by the WebUI model picker (`groups` / `default_model`)."""
    try:
        from jaeger_ai.core.models.discovery import canonical_runtime_inventory
        cat = canonical_runtime_inventory(instance_root)
        if cat.get("groups"):
            return {**cat, "source": "jaeger.runtime.truth"}
    except Exception:
        pass
    inv = provider_model_inventory(instance_root)
    groups = []
    for provider in inv["providers"]:
        if not provider.get("reachable"):
            continue
        models = []
        for m in provider.get("models") or []:
            name = str(m["id"])
            models.append({
                "id": name,
                "name": name,
                "label": name,
                "certifications": m.get("certifications") or {},
                "usable_for_react": m.get("usable_for_react"),
            })
        if models:
            groups.append({
                "provider": provider["display_name"],
                "provider_id": provider["id"],
                "status": "online",
                "models": models,
            })
    active = inv.get("active") or {}
    default_model = str(active.get("model") or "")
    return {
        "active_provider": active.get("provider") or "ollama",
        "default_model": default_model,
        "groups": groups,
        "source": "jaeger.runtime.truth",
    }


def _audio_truth() -> dict[str, Any]:
    from jaeger_ai.core.voice.status import voice_status

    status = voice_status()
    available = status["spoken_input"] or status["spoken_output"]
    return {
        "supported": status["stt"]["supported"] or status["tts"]["supported"],
        "configured": status["stt"]["configured"] or status["tts"]["configured"],
        "available": available,
        "spoken_input": status["spoken_input"],
        "spoken_output": status["spoken_output"],
        "reason": None if available else "no usable speech input or output on this machine",
        "detail": status,
    }


def capability_snapshot(instance_root: Path | None = None) -> dict[str, Any]:
    """Machine-readable capability truth. No secrets."""
    root = instance_root or _instance_root()
    frameworks = framework_inventory()
    models = provider_model_inventory(root)
    identity: dict[str, Any] = {}
    try:
        from jaeger_ai.core.entity.runtime import EntityRuntime
        rt = EntityRuntime.get_singleton()
        ident = getattr(rt, "identity", None)
        identity = {
            "entity_id": getattr(ident, "entity_id", None) if ident is not None else None,
            "mode": str(getattr(rt, "mode", "")),
            "resident": bool(getattr(rt, "is_resident", False)),
        }
    except Exception:
        identity = {"entity_id": None, "mode": "unknown", "resident": False}
    vision_certified = False
    for provider in models.get("providers") or []:
        for m in provider.get("models") or []:
            if str((m.get("certifications") or {}).get("VISION") or "").upper() == "PASS":
                vision_certified = True
    ollama_ok = any(p.get("id") == "ollama" and p.get("reachable") for p in models.get("providers") or [])
    return {
        "identity": {
            "supported": True,
            "configured": bool(identity.get("entity_id")),
            "available": bool(identity.get("entity_id")),
            "healthy": bool(identity.get("resident")),
            **identity,
        },
        "frameworks": {
            "supported": True,
            "configured": True,
            "available": True,
            "product_default": PRODUCT_DEFAULT_RUNTIME,
            "product_default_profile": PRODUCT_DEFAULT_PROFILE,
            "rows": frameworks,
        },
        "providers": {
            "supported": True,
            "configured": True,
            "available": ollama_ok,
            "inventory": models,
        },
        "models": {
            "supported": True,
            "configured": True,
            "available": bool((models.get("active") or {}).get("model")),
            "active": models.get("active"),
        },
        "cognition_roles": {
            "supported": True,
            "configured": True,
            "available": True,
            "certified": (models.get("active") or {}),
        },
        "vision": {
            "supported": True,
            "configured": vision_certified,
            "available": vision_certified,
            "authorized": True,
            "healthy": vision_certified,
            "certified": vision_certified,
            "reason": None if vision_certified else "no VISION-certified model on this instance",
        },
        "filesystem": {"supported": True, "configured": True, "available": True, "authorized": True},
        "shell": {"supported": True, "configured": True, "available": True, "authorized": True},
        "memory": {"supported": True, "configured": True, "available": True, "authorized": True},
        "remote_access": {"supported": True, "configured": True, "available": True, "authorized": True},
        "audio": _audio_truth(),
        "browser": {"supported": True, "configured": False, "available": False, "reason": "not probed in this snapshot"},
    }


def capability_prompt_block(instance_root: Path | None = None) -> str:
    snap = capability_snapshot(instance_root)
    active = (snap.get("models") or {}).get("active") or {}
    frameworks = [
        f"{row['display_name']} ({'ready' if row.get('available') else 'unavailable'})"
        for row in ((snap.get("frameworks") or {}).get("rows") or [])
    ]
    providers = []
    for p in ((snap.get("providers") or {}).get("inventory") or {}).get("providers") or []:
        if p.get("reachable"):
            providers.append(p["display_name"])
        else:
            providers.append(f"{p['display_name']}=unavailable")
    vision = snap.get("vision") or {}
    return (
        "# Runtime truth (authoritative; do not invent providers or frameworks):\n"
        f"- product_default_runtime={PRODUCT_DEFAULT_RUNTIME}\n"
        f"- entity_id={((snap.get('identity') or {}).get('entity_id'))}\n"
        f"- active_provider={active.get('provider')}\n"
        f"- active_model={active.get('model')}\n"
        f"- frameworks: {', '.join(frameworks)}\n"
        f"- providers: {', '.join(providers)}\n"
        f"- vision_available={bool(vision.get('available'))}"
        f" reason={vision.get('reason') or 'certified'}\n"
        "- Do not present unsupported or unconfigured providers as currently available."
    )


def attachment_id_for(session_id: str, stored_name: str, digest: str) -> str:
    raw = f"{session_id}:{stored_name}:{digest}".encode()
    return "att_" + hashlib.sha256(raw).hexdigest()[:16]
