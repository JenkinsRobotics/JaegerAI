"""Model discovery — what models are available, and where.

Surveys three sources so the TUI's ``/model`` command can show the full
picture at a glance:

  - **JROS registry** — GGUF models JROS runs in-process (downloaded or
    downloadable), via :mod:`model_resolver`.
  - **Ollama** — a local Ollama server's installed models (its
    ``/api/tags`` endpoint), when the server is running.
  - **LM Studio** — a local LM Studio server's models (its OpenAI-
    compatible ``/v1/models`` endpoint), when it is running.

Every server probe is best-effort with a short timeout: a server that
is not running yields an ``online: False`` status, never an exception.
The point is troubleshooting — being able to A/B the in-process model
against a separate local server to see which is at fault.
"""

from __future__ import annotations

import pathlib
from typing import Any

OLLAMA_URL = "http://localhost:11434"
LMSTUDIO_URL = "http://localhost:1234"
_PROBE_TIMEOUT = 1.5

# Where LM Studio keeps downloaded GGUF models (newer + older layouts).
_LMSTUDIO_DIRS = ("~/.lmstudio/models", "~/.cache/lm-studio/models")


def discover_jaeger() -> list[dict[str, Any]]:
    """JROS's own GGUF models — registered, with download/cache status."""
    try:
        from jaeger_os.core.models.model_resolver import list_registered_models
        return list_registered_models()
    except Exception:  # noqa: BLE001
        return []


def _scan_gguf(root: pathlib.Path, source: str) -> list[dict[str, Any]]:
    """Every ``*.gguf`` under ``root`` (recursive), tagged with ``source``."""
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    try:
        for p in sorted(root.rglob("*.gguf")):
            # mmproj-*.gguf are vision-projection companion files, not
            # standalone brains — never offer them as a model.
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
    """Custom GGUF directories from ``model.extra_gguf_dirs`` in the live
    instance config — added by the user or the agent through the
    ``model_location`` tool. Empty when no instance is bound."""
    try:
        from jaeger_os.main import _pipeline
        cfg = _pipeline.get("config")
        return [str(d) for d in (cfg.model.extra_gguf_dirs
                                 or [])]
    except Exception:  # noqa: BLE001
        return []


def discover_local_gguf() -> list[dict[str, Any]]:
    """Every ``.gguf`` file on disk JROS could load in-process — the
    repo ``models/`` dir, the JROS model cache, LM Studio's model
    folder, and any custom directories registered via ``model_location``
    (``model.extra_gguf_dirs`` in config). De-duplicated by absolute
    path; works with no server running (it is a pure filesystem scan)."""
    try:
        from jaeger_os.core.models.model_resolver import repo_models_dir, user_cache_dir
    except Exception:  # noqa: BLE001
        return []
    roots: list[tuple[pathlib.Path, str]] = []
    repo = repo_models_dir()
    if repo is not None:
        roots.append((repo, "repo models/"))
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
    """Every MLX-format model on disk. An MLX model is a *directory* (not
    a single file like GGUF): the HF layout — ``config.json`` plus one or
    more ``*.safetensors`` weight shards. LM Studio downloads its MLX
    picks into ``~/.lmstudio/models/<author>/<name>/`` with this layout,
    so the same scan picks them up. Returns the same shape ``local_gguf``
    returns so the picker can route either kind through one code path."""
    roots: list[tuple[pathlib.Path, str]] = []
    for lm in _LMSTUDIO_DIRS:
        roots.append((pathlib.Path(lm).expanduser(), "lm studio"))
    # HF hub cache uses snapshots/ symlinks — scan but de-dup by resolved path.
    hf_cache = pathlib.Path("~/.cache/huggingface/hub").expanduser()
    if hf_cache.is_dir():
        roots.append((hf_cache, "huggingface"))
    try:
        from jaeger_os.core.models.model_resolver import repo_models_dir, user_cache_dir
        repo = repo_models_dir()
        if repo is not None:
            roots.append((repo, "repo models/"))
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
        # rglob is bounded by depth in practice — MLX models live at
        # depth 2-4 under these roots (author/name/, or snapshots/<hash>/).
        for cfg in root.rglob("config.json"):
            mdir = cfg.parent
            try:
                resolved = str(mdir.resolve())
            except OSError:
                continue
            if resolved in seen:
                continue
            # A real MLX model has weights next to config.json.
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
    """Ollama models read from the on-disk manifest tree
    (``~/.ollama/models/manifests``) — works even when the Ollama
    server is not running. Returns ``[{name: 'model:tag'}, …]``."""
    base = pathlib.Path("~/.ollama/models/manifests").expanduser()
    if not base.is_dir():
        return []
    models: list[dict[str, Any]] = []
    try:
        # manifests/<registry>/<namespace>/<model>/<tag-file>
        for tag_file in sorted(base.rglob("*")):
            if not tag_file.is_file():
                continue
            model, tag = tag_file.parent.name, tag_file.name
            # Skip OS noise (.DS_Store, Thumbs.db) and hidden files.
            if model.startswith(".") or tag.startswith("."):
                continue
            models.append({"name": f"{model}:{tag}"})
    except Exception:  # noqa: BLE001
        pass
    return models


def _get_json(url: str) -> Any:
    import requests
    resp = requests.get(url, timeout=_PROBE_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def discover_ollama(base: str = OLLAMA_URL) -> dict[str, Any]:
    """Installed Ollama models via ``/api/tags``. Returns
    ``{online, models, endpoint}`` — ``online: False`` if not running."""
    try:
        data = _get_json(f"{base.rstrip('/')}/api/tags")
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "models": [], "endpoint": base,
                "detail": type(exc).__name__}
    models: list[dict[str, Any]] = []
    for m in (data.get("models") or []):
        if isinstance(m, dict) and m.get("name"):
            size = m.get("size")
            models.append({
                "name": m["name"],
                "size_gb": (round(size / 1e9, 1)
                            if isinstance(size, (int, float)) else None),
            })
    return {"online": True, "models": models, "endpoint": base}


def discover_lmstudio(base: str = LMSTUDIO_URL) -> dict[str, Any]:
    """LM Studio models via the OpenAI-compatible ``/v1/models``
    endpoint. Returns ``{online, models, endpoint}``."""
    try:
        data = _get_json(f"{base.rstrip('/')}/v1/models")
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "models": [], "endpoint": base,
                "detail": type(exc).__name__}
    models = [{"name": m["id"]} for m in (data.get("data") or [])
              if isinstance(m, dict) and m.get("id")]
    return {"online": True, "models": models, "endpoint": base}


OLLAMA_CLOUD_URL = "https://ollama.com/v1"
_CLOUD_TIMEOUT = 5.0


def discover_ollama_cloud(api_key: str = "") -> dict[str, Any]:
    """Ollama Cloud's model catalogue via the OpenAI-compatible
    ``/v1/models`` endpoint. Needs the API key. Returns
    ``{online, models, endpoint}`` — ``online: False`` (never an
    exception) when there is no key or the endpoint can't be reached."""
    if not api_key:
        return {"online": False, "models": [], "endpoint": OLLAMA_CLOUD_URL,
                "detail": "no api key"}
    try:
        import requests
        resp = requests.get(
            f"{OLLAMA_CLOUD_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_CLOUD_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "models": [], "endpoint": OLLAMA_CLOUD_URL,
                "detail": type(exc).__name__}
    models = [{"name": m["id"]} for m in (data.get("data") or [])
              if isinstance(m, dict) and m.get("id")]
    return {"online": True, "models": models, "endpoint": OLLAMA_CLOUD_URL}


def discover_all(ollama_cloud_key: str = "") -> dict[str, Any]:
    """The full picture so ``/model`` can show everything selectable:
    the JROS registry, every ``.gguf`` on disk (repo / cache / LM
    Studio), Ollama (live server + on-disk manifests), LM Studio's live
    server, and — when ``ollama_cloud_key`` is supplied — the Ollama
    Cloud catalogue."""
    ollama_live = discover_ollama()
    # Merge live Ollama models with the on-disk manifest list so models
    # show even when the server is down — de-duped by name.
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


# ── curated Ollama Cloud fallback ─────────────────────────────────────
# Live ``GET https://ollama.com/v1/models`` is unstable in practice — it
# 400s on some account configurations. The picker uses this list as a
# stable bottom-rank in its merge (live ∪ user-history ∪ curated) so the
# sub-menu is never empty just because the live endpoint is down. The
# user's typed picks (recorded via core.external_model_history) override
# this; this is the catalog floor.
OLLAMA_CLOUD_CURATED: tuple[str, ...] = (
    "qwen3.5:397b",
    "qwen3-coder:480b",
    "gpt-oss:120b",
    "gpt-oss:20b",
    "deepseek-v3.1:671b",
    "kimi-k2:1t",
)

# Same role for the other API providers — a stable bottom-rank used by the
# /model picker when the user has no history with the provider yet. Model
# names date faster than Ollama Cloud's, so keep these short and limit to
# the workhorses worth one click away.
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
