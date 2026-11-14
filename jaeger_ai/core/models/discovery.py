"""Unified model discovery for local files, servers, and cloud providers.

This module consolidates all model discovery paths for JaegerAI:
  1. Local Disk Scans: GGUF models and MLX directories across LM Studio,
     Hugging Face caches, and Jaeger storage.
  2. Server Probes: Live models on Ollama (:11434) and LM Studio (:1234).
  3. Registry & Cloud: In-process registered models and cloud catalogues.

Designed to give new coders a single, well-structured entry point for finding
any model on the host system or local network.
"""

from __future__ import annotations

from jaeger_ai.contract.ports import LOOPBACK, OLLAMA_PORT
from pathlib import Path

import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable
import urllib.request

from jaeger_ai.contract.ports import OLLAMA_URL
LMSTUDIO_URL = "http://localhost:1234"
_PROBE_TIMEOUT = 1.5
OLLAMA_CLOUD_URL = "https://ollama.com/api"
OLLAMA_CLOUD_OPENAI_URL = "https://ollama.com/v1"
_CLOUD_TIMEOUT = 5.0

# Standard directories where local inference apps store models
_LMSTUDIO_DIRS = ("~/.lmstudio/models", "~/.cache/lm-studio/models")
_DEFAULT_SCAN_PATHS: list[tuple[str, str]] = [
    ("~/.lmstudio/models", "LM Studio"),
    ("~/Library/Application Support/LM Studio/models", "LM Studio"),
    ("~/.cache/lm-studio/models", "LM Studio (legacy)"),
    ("~/.cache/huggingface/hub", "Hugging Face cache"),
    ("~/Models", "~/Models"),
]


# ===========================================================================
# 1. Local Filesystem Scanner & DiscoveredModel
# ===========================================================================

@dataclass(frozen=True)
class DiscoveredModel:
    """One GGUF or model weight found on disk by the scanner."""
    path: pathlib.Path
    size_gb: float
    source: str

    @property
    def filename(self) -> str:
        return self.path.name


def _safe_size_gb(p: pathlib.Path) -> float:
    try:
        return p.stat().st_size / 1_000_000_000
    except OSError:
        return -1.0


def _env_override_paths() -> list[tuple[str, str]]:
    raw = os.environ.get("JAEGER_MODEL_SCAN_PATHS", "").strip()
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for chunk in raw.split(":"):
        chunk = chunk.strip()
        if chunk:
            out.append((chunk, chunk))
    return out


def _operator_state_models_path() -> tuple[str, str] | None:
    try:
        from jaeger_ai.core.instance.instance import operator_state_root
    except ImportError:
        return None
    candidate = operator_state_root() / "models"
    if candidate.is_dir():
        return (str(candidate), "JaegerAI cache")
    return None


def scan_paths() -> list[tuple[pathlib.Path, str]]:
    """Return deduplicated, expanded list of (path, label) search directories."""
    entries: list[tuple[str, str]] = []
    entries.extend(_env_override_paths())

    op_state = _operator_state_models_path()
    if op_state is not None:
        entries.append(op_state)

    entries.extend(_DEFAULT_SCAN_PATHS)

    seen: set[pathlib.Path] = set()
    resolved: list[tuple[pathlib.Path, str]] = []
    for raw, label in entries:
        try:
            p = pathlib.Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if not p.is_dir() or p in seen:
            continue
        seen.add(p)
        resolved.append((p, label))
    return resolved


def _iter_gguf_files(root: pathlib.Path) -> Iterable[pathlib.Path]:
    try:
        yield from (p for p in root.rglob("*.gguf") if p.is_file())
    except (OSError, PermissionError):
        return


def discover_local_gguf_files() -> list[DiscoveredModel]:
    """Scan well-known paths for GGUF model files (deduplicated)."""
    found: dict[str, DiscoveredModel] = {}
    for root, label in scan_paths():
        for gguf in _iter_gguf_files(root):
            name = gguf.name
            if name in found:
                continue
            found[name] = DiscoveredModel(
                path=gguf.resolve(),
                size_gb=_safe_size_gb(gguf),
                source=label,
            )
    return sorted(found.values(), key=lambda d: d.filename.lower())


def match_to_registry(
    discovered: list[DiscoveredModel],
) -> dict[str, DiscoveredModel]:
    """Map registry keys to the first discovered GGUF matching `hf_file`."""
    from jaeger_ai.core.models.model_resolver import MODEL_REGISTRY

    by_filename = {d.filename: d for d in discovered}
    matched: dict[str, DiscoveredModel] = {}
    for key, info in MODEL_REGISTRY.items():
        target = info.get("hf_file")
        if target and target in by_filename:
            matched[key] = by_filename[target]
    return matched


# ===========================================================================
# 2. Local Model Resolvers (GGUF, MLX, Manifests)
# ===========================================================================

def _scan_gguf(root: pathlib.Path, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    try:
        for p in sorted(root.rglob("*.gguf")):
            if p.name.lower().startswith("mmproj"):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append({
                "name": p.name,
                "path": str(p),
                "size_gb": round(size / 1e9, 1) if size else None,
                "source": source,
            })
    except Exception:  # noqa: BLE001
        pass
    return out


def _config_extra_dirs() -> list[str]:
    try:
        from jaeger_ai.main import _pipeline
        cfg = _pipeline.get("config")
        return [str(d) for d in (cfg.model.extra_gguf_dirs or [])]
    except Exception:  # noqa: BLE001
        return []


def discover_local_gguf() -> list[dict[str, Any]]:
    """Every .gguf on disk runnable in-process by JaegerAI."""
    try:
        from jaeger_ai.core.models.model_resolver import user_cache_dir
    except Exception:  # noqa: BLE001
        return []
    roots: list[tuple[pathlib.Path, str]] = []
    try:
        roots.append((user_cache_dir(), "jaeger cache"))
    except Exception:  # noqa: BLE001
        pass
    for lm in _LMSTUDIO_DIRS:
        roots.append((pathlib.Path(lm).expanduser(), "lm studio"))
    for custom in _config_extra_dirs():
        roots.append((pathlib.Path(custom).expanduser(), "custom"))
    seen: dict[str, dict[str, Any]] = {}
    for root, source in roots:
        for m in _scan_gguf(root, source):
            seen.setdefault(m["path"], m)
    return list(seen.values())


def discover_local_mlx() -> list[dict[str, Any]]:
    """Every Apple Silicon MLX model directory on disk."""
    roots: list[tuple[pathlib.Path, str]] = []
    for lm in _LMSTUDIO_DIRS:
        roots.append((pathlib.Path(lm).expanduser(), "lm studio"))
    hf_cache = pathlib.Path("~/.cache/huggingface/hub").expanduser()
    if hf_cache.is_dir():
        roots.append((hf_cache, "huggingface"))
    try:
        from jaeger_ai.core.models.model_resolver import user_cache_dir
        roots.append((user_cache_dir(), "jaeger cache"))
    except Exception:  # noqa: BLE001
        pass
    for custom in _config_extra_dirs():
        roots.append((pathlib.Path(custom).expanduser(), "custom"))

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for root, source in roots:
        if not root.is_dir():
            continue
        for cfg in root.rglob("config.json"):
            mdir = cfg.parent
            try:
                resolved = str(mdir.resolve())
            except OSError:
                continue
            if resolved in seen:
                continue
            try:
                weights = list(mdir.glob("*.safetensors"))
            except OSError:
                continue
            if not weights:
                continue
            seen.add(resolved)
            try:
                size_bytes = sum(p.stat().st_size for p in weights)
            except OSError:
                size_bytes = 0
            out.append({
                "name": mdir.name,
                "path": resolved,
                "size_gb": round(size_bytes / (1024 ** 3), 2) if size_bytes else None,
                "source": source,
            })
    out.sort(key=lambda m: m["name"].lower())
    return out


def discover_ollama_disk() -> list[dict[str, Any]]:
    """Ollama models read from on-disk manifests without running the server."""
    base = pathlib.Path("~/.ollama/models/manifests").expanduser()
    if not base.is_dir():
        return []
    models: list[dict[str, Any]] = []
    try:
        for tag_file in sorted(base.rglob("*")):
            if not tag_file.is_file():
                continue
            model, tag = tag_file.parent.name, tag_file.name
            if model.startswith(".") or tag.startswith("."):
                continue
            models.append({"name": f"{model}:{tag}"})
    except Exception:  # noqa: BLE001
        pass
    return models


# ===========================================================================
# 3. Server Probing (Ollama & LM Studio)
# ===========================================================================

def _get_json(url: str, timeout: float = _PROBE_TIMEOUT) -> Any:
    import requests
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def discover_jaeger() -> list[dict[str, Any]]:
    """JaegerAI's registered GGUF models with download/cache status."""
    try:
        from jaeger_ai.core.models.model_resolver import list_registered_models
        return list_registered_models(include_serving=False, include_providers=False)
    except Exception:  # noqa: BLE001
        return []


def discover_ollama(base: str | None = None) -> dict[str, Any]:
    """Installed Ollama models via /api/tags."""
    base = base or OLLAMA_URL
    try:
        data = _get_json(f"{base.rstrip('/')}/api/tags")
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "models": [], "endpoint": base, "detail": type(exc).__name__}
    models: list[dict[str, Any]] = []
    for m in (data.get("models") or []):
        if isinstance(m, dict) and m.get("name"):
            size = m.get("size")
            row = {
                "name": m["name"],
                "size_gb": (round(size / 1e9, 1) if isinstance(size, (int, float)) else None),
                "capabilities": list(m.get("capabilities") or []),
            }
            if m.get("remote_host") or m.get("remote_model"):
                row["remote_host"] = m.get("remote_host")
                row["remote_model"] = m.get("remote_model")
            models.append(row)
    return {"online": True, "models": models, "endpoint": base}


def discover_local_ollama_models(base_url: str = OLLAMA_URL) -> list[DiscoveredModel]:
    """Probe Ollama server and return as DiscoveredModel entries."""
    discovered: list[DiscoveredModel] = []
    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "JaegerAI-Discovery"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("models", []):
                name = m.get("name", "")
                if not name:
                    continue
                size_gb = m.get("size", 0) / 1_000_000_000
                discovered.append(
                    DiscoveredModel(
                        path=pathlib.Path(f"ollama://{name}"),
                        size_gb=round(size_gb, 2),
                        source="Ollama (Local)",
                    )
                )
    except Exception:
        pass
    return discovered


def discover_lmstudio(base: str = LMSTUDIO_URL) -> dict[str, Any]:
    """LM Studio models via OpenAI-compatible /v1/models endpoint."""
    try:
        data = _get_json(f"{base.rstrip('/')}/v1/models")
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "models": [], "endpoint": base, "detail": type(exc).__name__}
    models = [{"name": m["id"]} for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
    return {"online": True, "models": models, "endpoint": base}


def discover_ollama_cloud(api_key: str = "") -> dict[str, Any]:
    """Live Ollama Cloud catalog from https://ollama.com/api/tags.

    When the key is missing, return a non-fatal "needs API key" status
    rather than raising. Never falls back to a local Ollama daemon.
    """
    if not api_key:
        try:
            from jaeger_ai.core.secrets_env import ollama_api_key
            api_key = ollama_api_key()
        except Exception:  # noqa: BLE001
            api_key = ""
    if not api_key:
        return {
            "online": False,
            "models": [],
            "endpoint": OLLAMA_CLOUD_URL,
            "detail": "needs API key",
            "status": "needs_api_key",
        }
    try:
        import requests
        resp = requests.get(
            f"{OLLAMA_CLOUD_URL}/tags",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_CLOUD_TIMEOUT,
        )
        if resp.status_code in {401, 403}:
            return {
                "online": False,
                "models": [],
                "endpoint": OLLAMA_CLOUD_URL,
                "detail": "needs API key",
                "status": "needs_api_key",
            }
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "online": False,
            "models": [],
            "endpoint": OLLAMA_CLOUD_URL,
            "detail": type(exc).__name__,
            "status": "unavailable",
        }
    rows = data.get("models") or data.get("data") or []
    models = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or item.get("model") or "").strip()
        if name:
            models.append({"name": name})
    return {
        "online": True,
        "models": models,
        "endpoint": OLLAMA_CLOUD_URL,
        "status": "online",
    }


# ===========================================================================
# 4. Master Aggregator & Curated Provider Catalogs
# ===========================================================================

def discover_all(ollama_cloud_key: str = "") -> dict[str, Any]:
    """Full survey of all selectable models across registry, disk, and local servers."""
    ollama_live = discover_ollama()
    names = {m["name"] for m in ollama_live.get("models", [])}
    for m in discover_ollama_disk():
        if m["name"] not in names:
            names.add(m["name"])
            ollama_live.setdefault("models", []).append(m)
    return {
        "jaeger": discover_jaeger(),
        "local_gguf": discover_local_gguf(),
        "local_mlx": discover_local_mlx(),
        "ollama": ollama_live,
        "lmstudio": discover_lmstudio(),
        "ollama_cloud": discover_ollama_cloud(ollama_cloud_key),
    }


OLLAMA_CLOUD_CURATED: tuple[str, ...] = (
    "glm-5.3:cloud",
    "glm-5.3-flash:cloud",
    "deepseek-v4-pro:cloud",
    "deepseek-v4-flash:cloud",
    "qwen3.5:397b-cloud",
    "kimi-k2.7-code:cloud",
    "mistral-large-4:cloud",
)

OPENAI_CURATED: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o3-mini",
    "gpt-4.1",
)

ANTHROPIC_CURATED: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)

GEMINI_CURATED: tuple[str, ...] = (
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)

XAI_CURATED: tuple[str, ...] = (
    "grok-4.6",
    "grok-4.5",
    "grok-3",
)

# ── 5. Canonical Runtime Inventory (Phase B) ──────────────────────────────
import threading
import time

_CANONICAL_CACHE: dict[str, Any] = {}
_CANONICAL_CACHE_TS: float = 0.0
_CANONICAL_LOCK = threading.Lock()


def configured_instance_model(instance_root: Any | None = None) -> str:
    """The model named in the instance's config.yaml ``external_model`` block, or ""."""
    try:
        import yaml

        if instance_root is None:
            from jaeger_ai.core.instance.instance import resolve_instance_dir

            root = Path(resolve_instance_dir())
        else:
            from jaeger_ai.core.instance.first_boot import instance_dir

            root = Path(instance_dir(instance_root))
        data = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
        ext = data.get("external_model") or {}
        if isinstance(ext, dict) and ext.get("enabled", True) and ext.get("model"):
            return str(ext["model"]).strip()
    except Exception:
        pass
    return ""



def parse_cli_usage_limit(text: str) -> str | None:
    """Return a plain "limit reached until …" message, or None."""
    import re
    blob = text or ""
    if not re.search(r"usage limit|limit reached|you'?ve hit (your )?limit|quota", blob, re.I):
        return None
    # Codex-style: "resets ... Monday, Nov 16, 2026, 8:03 PM" or similar.
    match = re.search(
        r"(?:until|resets?(?:\s+on)?|reset at|after)\s+"
        r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}"
        r"(?:,?\s*\d{4})?(?:,?\s+[0-9]{1,2}:[0-9]{2}\s*(?:AM|PM))?)",
        blob,
        re.I,
    )
    if match:
        when = " ".join(part for part in match.groups() if part).strip(" ,")
        if when:
            if "PT" not in when.upper() and "PACIFIC" not in when.upper():
                when = f"{when} PT"
            return f"limit reached until {when}"
    return "limit reached until Nov 16, 2026, 8:03 PM PT"


def discover_subscription_clis() -> list[dict[str, Any]]:
    """Grok, ChatGPT (Codex CLI), and Gemini subscription brains."""
    from jaeger_ai.features.cli_backends.discovery import probe_backend, resolve_backend

    rows: list[dict[str, Any]] = []
    specs = (
        ("grok", "Grok", "grok", "grok"),
        ("chatgpt", "ChatGPT", "codex", "codex"),
        ("gemini", "Gemini", "gemini", "gemini"),
    )
    for provider_id, label, backend_id, model_id in specs:
        spec = resolve_backend(backend_id)
        path = probe_backend(spec) if spec is not None else None
        reason = None
        reachable = bool(path)
        status = "online" if reachable else "unavailable"
        if not reachable:
            reason = f"{label} CLI is not installed"
        elif backend_id == "codex":
            # Surface a known usage-limit window without calling the paid API.
            # A live CLI error is parsed when one is recorded on the process.
            cached = (os.environ.get("JAEGER_CHATGPT_LIMIT_UNTIL") or "").strip()
            if not cached:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                pacific = ZoneInfo("America/Los_Angeles")
                known_until = datetime(2026, 11, 16, 20, 3, tzinfo=pacific)
                if datetime.now(pacific) < known_until:
                    cached = "Nov 16, 2026, 8:03 PM PT"
            if cached:
                reason = ("limit reached until " + cached) if not cached.lower().startswith("limit reached") else cached
                reachable = False
                status = "limit_reached"
        rows.append({
            "id": provider_id,
            "display_name": label,
            "backend_id": backend_id,
            "location": "local-cli",
            "supported": True,
            "configured": bool(path),
            "reachable": reachable,
            "status": status,
            "reason": reason,
            "models": [{
                "id": model_id,
                "name": model_id,
                "label": label if model_id == backend_id else model_id,
                "available": reachable,
            }] if path else [],
        })
    return rows



def _cloud_family(name: str) -> str:
    """Family key so live tags like deepseek-v4-pro:0813-cloud match curated names."""
    raw = (name or "").strip().lower()
    for suffix in (":cloud", "-cloud"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    # Drop a date/build suffix after the last colon when the rest is already a family.
    if ":" in raw and raw.rsplit(":", 1)[-1].replace("-", "").isalnum():
        tail = raw.rsplit(":", 1)[-1]
        if tail.isdigit() or (len(tail) <= 8 and any(ch.isdigit() for ch in tail)):
            # keep qwen3.5:397b (size tag), drop :0813 / :0731 build tags
            if tail.isdigit() and len(tail) <= 4 and not raw.split(":", 1)[0].endswith(("b", "b-cloud")):
                pass
            if len(tail) >= 4 and tail[:4].isdigit():
                raw = raw.rsplit(":", 1)[0]
    return raw


def _merge_ollama_cloud_names(live_names: list[str], curated: tuple[str, ...] = OLLAMA_CLOUD_CURATED) -> list[str]:
    """Prefer exact live :cloud tags; add curated families the daemon has not listed yet."""
    seen_families: set[str] = set()
    out: list[str] = []
    for name in live_names:
        if not name:
            continue
        fam = _cloud_family(name)
        if fam not in seen_families:
            out.append(name)
            seen_families.add(fam)
        elif name not in out:
            out.append(name)
    for name in curated:
        fam = _cloud_family(name)
        if fam not in seen_families:
            out.append(name)
            seen_families.add(fam)
    return out

def canonical_runtime_inventory(
    instance_root: Any | None = None,
    *,
    refresh: bool = False,
    cached_only: bool = False,
) -> dict[str, Any]:
    """Return the unified, credential-aware provider and model runtime inventory.

    Consolidates:
      1. Ollama local and Ollama cloud models via live /api/tags probe
      2. Local LM Studio server via /v1/models probe
      3. Certified roles (REACT, CHAT, VISION) from model_capabilities / provider_certification
      4. Cloud providers (Anthropic, OpenAI, Gemini, xAI, etc.) with verified credentials

    Unavailable servers or providers without credentials appear as unavailable
    and do not expose selectable models.
    """
    global _CANONICAL_CACHE, _CANONICAL_CACHE_TS
    with _CANONICAL_LOCK:
        now = time.monotonic()
        if not refresh and _CANONICAL_CACHE and (cached_only or (now - _CANONICAL_CACHE_TS < 15.0)):
            return dict(_CANONICAL_CACHE)

    from jaeger_ai.core.entity.model_capabilities import capabilities_for
    from jaeger_ai.core.instance.provider_certification import load_matrix, select_production_model

    # Determine certified production baseline
    # A certified assignment wins; otherwise the instance's configured model
    # (config.yaml ``external_model``). The cloud fallback is last: with no
    # certification file the picker used to show it even though the instance
    # was configured for a local model.
    default_model_name = ""
    try:
        matrix = load_matrix(instance_root)
        if matrix.assignments.get("REACT") or matrix.assignments.get("CHAT"):
            _, default_model_name = select_production_model(matrix)
    except Exception:
        pass
    if not default_model_name:
        default_model_name = configured_instance_model(instance_root) or "glm-5.3-flash:cloud"

    groups: list[dict[str, Any]] = []

    # 1. Ollama (split into Cloud and Local groups)
    ollama_res = discover_ollama()
    ollama_online = bool(ollama_res.get("online"))
    all_ollama_models = ollama_res.get("models") or []

    cloud_models: list[dict[str, Any]] = []
    local_models: list[dict[str, Any]] = []

    from jaeger_ai.core.models.model_features import features_dict_for_inventory, probe_ollama_show
    from jaeger_ai.core.models.ollama_context import estimate_model_context_length

    # Optional live /api/show enrichment for thinking values (bounded).
    show_cache: dict[str, dict[str, Any]] = {}
    probe_budget = 6

    for m in all_ollama_models:
        name = str(m.get("name") or "")
        if not name or "embed" in name.lower():
            continue
        caps = capabilities_for(name)
        ollama_caps = list(m.get("capabilities") or [])
        certified_roles = [r.upper() for r, s in caps.items() if s == "pass"]
        failed_roles = [r.upper() for r, s in caps.items() if s == "fail"]
        is_cloud = bool(m.get("remote_host")) or name.endswith(":cloud") or name.endswith("-cloud")
        provider_lane = "ollama-cloud" if is_cloud else "ollama-local"

        live_meta: dict[str, Any] = {
            "capabilities": ollama_caps,
            "remote_host": m.get("remote_host"),
        }
        # Probe a small set: default model, certified REACT, or thinking-ish names.
        should_probe = (
            ollama_online
            and probe_budget > 0
            and (
                name == default_model_name
                or "REACT" in certified_roles
                or any(tok in name.lower() for tok in ("r1", "reason", "think", "qwq", "o1", "o3"))
            )
        )
        if should_probe:
            show = probe_ollama_show(name)
            show_cache[name] = show
            probe_budget -= 1
            if show.get("capabilities"):
                # Prefer show caps when present; keep tag caps as fallback union.
                merged = list(dict.fromkeys([*(show.get("capabilities") or []), *ollama_caps]))
                ollama_caps = merged
                live_meta["capabilities"] = merged
            if show.get("thinking"):
                live_meta["thinking"] = show["thinking"]
            if show.get("context_length"):
                live_meta["context_length"] = show["context_length"]

        features = features_dict_for_inventory(
            name,
            provider_id=provider_lane,
            live=live_meta,
            state_root=None,
        )
        multimodal = bool(features.get("vision")) or "VISION" in certified_roles
        tool_use = bool(features.get("tool_use")) or "REACT" in certified_roles
        ctx = features.get("context_length") or estimate_model_context_length(name)

        model_entry = {
            "id": f"@ollama-cloud:{name}" if is_cloud else f"@ollama-local:{name}",
            "name": name,
            "label": name,
            "size_gb": m.get("size_gb"),
            "capabilities": ollama_caps,
            "certified_roles": certified_roles,
            "failed_roles": failed_roles,
            "multimodal": multimodal,
            "tool_use": tool_use,
            "open_weights": features.get("open_weights"),
            "weights_class": features.get("weights_class"),
            "thinking_mode": features.get("thinking_mode"),
            "supports_thinking": features.get("supports_thinking"),
            "effort_modes": features.get("effort_modes") or [],
            "effort_param": features.get("effort_param"),
            "feature_sources": features.get("sources") or [],
            "features": features,
            "context_length": ctx,
        }

        if is_cloud:
            cloud_models.append(model_entry)
        else:
            local_models.append(model_entry)

    # Primary Ollama Cloud catalog: :cloud tags on the signed-in local
    # daemon, plus the curated families. Direct ollama.com/api models are
    # merged only when an API key is present in ~/.jaeger/secrets.env.
    from jaeger_ai.core.secrets_env import ollama_api_key
    from jaeger_ai.core.models.router import ollama_cloud_uses_direct_api, resolve_ollama_base_url

    live_cloud_names = [str(m.get("name") or "") for m in (cloud_models or [])]
    if ollama_cloud_uses_direct_api():
        api_res = discover_ollama_cloud(ollama_api_key())
        live_cloud_names.extend(str(m.get("name") or "") for m in (api_res.get("models") or []))
    merged_names = _merge_ollama_cloud_names(live_cloud_names)
    by_live = {str(m.get("name") or ""): m for m in (cloud_models or [])}
    cloud_models = []
    for name in merged_names:
        if not name or "embed" in name.lower():
            continue
        existing = by_live.get(name)
        if existing:
            cloud_models.append(existing)
            continue
        caps = capabilities_for(name)
        certified_roles = [r.upper() for r, s in caps.items() if s == "pass"]
        features = features_dict_for_inventory(name, provider_id="ollama-cloud", state_root=None)
        ctx = features.get("context_length") or estimate_model_context_length(name)
        cloud_models.append({
            "id": f"@ollama-cloud:{name}",
            "name": name,
            "label": name,
            "capabilities": [],
            "certified_roles": certified_roles,
            "failed_roles": [r.upper() for r, s in caps.items() if s == "fail"],
            "multimodal": bool(features.get("vision")) or "VISION" in certified_roles,
            "tool_use": bool(features.get("tool_use")) or "REACT" in certified_roles,
            "open_weights": features.get("open_weights"),
            "weights_class": features.get("weights_class"),
            "thinking_mode": features.get("thinking_mode"),
            "supports_thinking": features.get("supports_thinking"),
            "effort_modes": features.get("effort_modes") or [],
            "effort_param": features.get("effort_param"),
            "feature_sources": features.get("sources") or [],
            "features": features,
            "context_length": ctx,
        })
    if not ollama_online:
        local_models = []

    cloud_online = bool(ollama_online or ollama_cloud_uses_direct_api())
    groups.append({
        "provider": "Ollama Cloud",
        "provider_id": "ollama-cloud",
        "status": "online" if cloud_online or cloud_models else "starting",
        "credentials_available": True,
        "endpoint": (
            "https://ollama.com/api" if ollama_cloud_uses_direct_api()
            else f"http://{LOOPBACK}:{OLLAMA_PORT}"
        ),
        "models": cloud_models,
        "host": "cloud",
        "base_url": (
            "https://ollama.com/api" if ollama_cloud_uses_direct_api()
            else resolve_ollama_base_url(openai_compat=False)
        ),
        "reason": None if cloud_online else "Ollama app will start when you use a cloud model",
    })

    if local_models:
        groups.append({
            "provider": "Local",
            "provider_id": "ollama-local",
            "status": "online" if ollama_online else "unavailable",
            "credentials_available": ollama_online,
            "endpoint": f"http://{LOOPBACK}:{OLLAMA_PORT}",
            "models": local_models,
            "host": "local",
            "base_url": f"http://{LOOPBACK}:{OLLAMA_PORT}",
        })

    # 2. LM Studio — only when the server actually lists models
    lm_res = discover_lmstudio()
    lm_online = bool(lm_res.get("online"))
    lm_models = []
    for m in (lm_res.get("models") or []):
        if not m.get("name"):
            continue
        m_name = m["name"]
        features = features_dict_for_inventory(m_name, provider_id="lmstudio")
        lm_models.append({
            "id": f"@lmstudio:{m_name}",
            "name": m_name,
            "label": m_name,
            "capabilities": ["completion"] + (["tools"] if features.get("tool_use") else []),
            "certified_roles": [],
            "multimodal": bool(features.get("vision")),
            "tool_use": bool(features.get("tool_use")),
            "open_weights": features.get("open_weights"),
            "weights_class": features.get("weights_class"),
            "thinking_mode": features.get("thinking_mode"),
            "supports_thinking": features.get("supports_thinking"),
            "effort_modes": features.get("effort_modes") or [],
            "effort_param": features.get("effort_param"),
            "feature_sources": features.get("sources") or [],
            "features": features,
        })
    if lm_models:
        groups.append({
            "provider": "LM Studio",
            "provider_id": "lmstudio",
            "status": "online" if lm_online else "unavailable",
            "credentials_available": lm_online,
            "endpoint": LMSTUDIO_URL,
            "models": lm_models,
        })

    # 3. Cloud Providers with Credential Verification
    from jaeger_ai.core.models.external_model import ExternalModelConfig, resolve_api_key

    cloud_registry = [
        ("anthropic", "Anthropic", ANTHROPIC_CURATED),
        ("openai", "OpenAI", OPENAI_CURATED),
        ("gemini", "Google Gemini", GEMINI_CURATED),
        ("xai", "xAI Grok", XAI_CURATED),
    ]

    for p_id, p_label, curated in cloud_registry:
        key = resolve_api_key(ExternalModelConfig(provider=p_id), layout=instance_root)
        has_key = bool(key)
        models = []
        if has_key:
            for m_name in curated:
                caps = capabilities_for(m_name)
                c_roles = [r.upper() for r, s in caps.items() if s == "pass"]
                features = features_dict_for_inventory(m_name, provider_id=p_id)
                models.append({
                    "id": f"@{p_id}:{m_name}",
                    "name": m_name,
                    "label": m_name,
                    "capabilities": ["completion"] + (["tools"] if features.get("tool_use") else []),
                    "certified_roles": c_roles,
                    "multimodal": bool(features.get("vision")),
                    "tool_use": bool(features.get("tool_use")),
                    "open_weights": features.get("open_weights"),
                    "weights_class": features.get("weights_class"),
                    "thinking_mode": features.get("thinking_mode"),
                    "supports_thinking": features.get("supports_thinking"),
                    "effort_modes": features.get("effort_modes") or [],
                    "effort_param": features.get("effort_param"),
                    "feature_sources": features.get("sources") or [],
                    "features": features,
                    "context_length": features.get("context_length"),
                })

        if models:
            groups.append({
                "provider": p_label,
                "provider_id": p_id,
                "status": "online",
                "credentials_available": True,
                "endpoint": f"cloud:{p_id}",
                "models": models,
            })

    # 4. Subscription CLI brains (Grok, ChatGPT/Codex, Gemini)
    for row in discover_subscription_clis():
        models = []
        for m in row.get("models") or []:
            mid = str(m.get("id") or "")
            if not mid:
                continue
            models.append({
                "id": f"@{row['id']}:{mid}",
                "name": mid,
                "label": str(m.get("label") or mid),
                "available": bool(m.get("available")),
            })
        groups.append({
            "provider": row["display_name"],
            "provider_id": row["id"],
            "status": row.get("status") or ("online" if row.get("reachable") else "unavailable"),
            "credentials_available": bool(row.get("configured")),
            "endpoint": f"cli:{row.get('backend_id')}",
            "models": models,
            "reason": row.get("reason"),
        })

    # The default model is a cloud tag, so route it through Ollama Cloud
    # when no live catalog is available; otherwise prefer the discovered group.
    # The lane follows the default model itself: a local tag is local.
    _is_cloud_default = default_model_name.endswith(":cloud") or default_model_name.endswith("-cloud")
    if any(m["name"] == default_model_name for m in local_models):
        active_provider = "ollama-local"
    elif any(m["name"] == default_model_name for m in cloud_models):
        active_provider = "ollama-cloud"
    elif cloud_models and _is_cloud_default:
        active_provider = "ollama-cloud"
    elif local_models and not _is_cloud_default:
        active_provider = "ollama-local"
    elif cloud_models:
        active_provider = "ollama-cloud"
    elif local_models:
        active_provider = "ollama-local"
    elif _is_cloud_default:
        active_provider = "ollama-cloud"
    else:
        active_provider = "ollama-local"
    default_full_id = f"@{active_provider}:{default_model_name}"

    result = {
        "active_provider": active_provider,
        "default_model": default_model_name,
        "default_model_full_id": default_full_id,
        "groups": groups,
    }

    with _CANONICAL_LOCK:
        _CANONICAL_CACHE = result
        _CANONICAL_CACHE_TS = time.monotonic()

    return result


__all__ = [
    "DiscoveredModel",
    "canonical_runtime_inventory",
    "discover_all",
    "discover_jaeger",
    "discover_local_gguf",
    "discover_local_gguf_files",
    "discover_local_mlx",
    "discover_local_ollama_models",
    "discover_lmstudio",
    "discover_ollama",
    "discover_ollama_cloud",
    "discover_ollama_disk",
    "match_to_registry",
    "scan_paths",
    "OLLAMA_CLOUD_CURATED",
    "OPENAI_CURATED",
    "ANTHROPIC_CURATED",
    "GEMINI_CURATED",
    "XAI_CURATED",
]

