"""Model-management tools — the agent's view of available LLMs.

  • list_models()             — registered models + cache status (read-only)
  • download_model(name)      — fetch a registered model from HF Hub
  • model_location(action, …) — register a custom GGUF directory to scan

Design intent (2026-05-19): the agent must NOT download models silently
on its own. ``download_model`` is gated at ``PRIVILEGED`` (tier 4) so it
routes through the permission confirmation flow — it only runs when the
user explicitly asks for a model, or agrees to one the agent recommended
in conversation. ``list_models`` is read-only (tier 0) so the agent can
freely tell the user what's available and make a recommendation.

The FRAMEWORK still auto-downloads a missing model when one is needed
for boot / switch_model — that's plumbing, not an agent decision. These
tools are the *deliberate* path: the agent choosing, with the user, to
fetch a model.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


def list_models() -> dict[str, Any]:
    """List every model in the registry with its role (realtime / coder)
    and cache status (ready / not downloaded). Read-only — use this to
    tell the user what's available or to back a recommendation."""
    from jaeger_os.core.models.model_resolver import MODEL_REGISTRY, list_registered_models
    rows = list_registered_models()
    for r in rows:
        entry = MODEL_REGISTRY.get(r["name"], {})
        r["role"] = entry.get("role", "unknown")
    return {"models": rows, "count": len(rows)}


@requires_tier(
    PermissionTier.PRIVILEGED,
    skill="models",
    operation="download_model",
    summary="download a model (large — multiple GB) from HuggingFace Hub",
)
def download_model(name: str) -> dict[str, Any]:
    """Download a registered model into the user model cache.

    Tier-4 (PRIVILEGED): a model is a multi-GB download, so this routes
    through the permission confirmation flow — it runs only when the
    user has agreed (either by asking directly or approving a model you
    recommended). Do NOT call this speculatively; recommend first, let
    the user decide, then call it.

    ``name`` must be a key in the model registry — call ``list_models``
    to see valid names. Returns ``{ok, model, path}`` on success or
    ``{ok: False, error: ...}``."""
    from jaeger_os.core.models.model_resolver import MODEL_REGISTRY
    from jaeger_os.core.models.model_resolver import download_model as _download

    key = (name or "").strip()
    if key not in MODEL_REGISTRY:
        return {
            "ok": False,
            "model": key,
            "error": (f"unknown model {key!r}; call list_models() for the "
                      f"registry. Known: {sorted(MODEL_REGISTRY.keys())}"),
        }
    try:
        path = _download(key, progress=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "model": key, "error": str(exc)}
    return {"ok": True, "model": key, "path": str(path)}


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="models",
    operation="model_location",
    summary="register or remove a custom directory scanned for GGUF models",
)
def model_location(action: str, path: str = "") -> dict[str, Any]:
    """Manage the extra directories JROS scans for local ``.gguf`` models.

    Beyond the built-in scan paths (the repo ``models/``, the JROS
    cache, LM Studio's folder), register any folder of GGUF files so it
    appears in ``/models`` and the ``/model`` picker — including, e.g.,
    a non-standard Ollama or LM Studio install.

      - ``action="add"``    — register ``path`` (an existing directory).
      - ``action="remove"`` — unregister ``path``.
      - ``action="list"``   — show the currently-registered directories.

    The set is persisted to the instance config (``model.extra_gguf_dirs``)
    so it survives restarts. Tier-1 (WRITE_LOCAL) — it edits the
    instance config. This is the agent-safe way to extend the model
    scan set: config + a tool, no core-file editing."""
    import pathlib

    from jaeger_os.core.instance.schemas import dump_yaml

    from jaeger_os.core.context import _require_layout

    act = (action or "").strip().lower()
    try:
        from jaeger_os.main import _pipeline
        cfg = _pipeline.get("config")
    except Exception:  # noqa: BLE001
        cfg = None
    if cfg is None:
        return {"ok": False, "error": "no active instance config"}

    dirs = list(cfg.model.extra_gguf_dirs or [])

    if act in ("list", "show", ""):
        return {"ok": True, "action": "list", "extra_gguf_dirs": dirs}

    if act not in ("add", "remove", "rm", "delete"):
        return {"ok": False,
                "error": f"unknown action {action!r} — use add / remove / list"}

    clean = (path or "").strip()
    if not clean:
        return {"ok": False, "error": f"{act} needs a path"}
    resolved = str(pathlib.Path(clean).expanduser())

    if act == "add":
        if not pathlib.Path(resolved).is_dir():
            return {"ok": False, "error": f"not a directory: {resolved}"}
        if resolved in dirs:
            return {"ok": True, "action": "add", "note": "already registered",
                    "extra_gguf_dirs": dirs}
        dirs.append(resolved)
    else:  # remove
        if resolved not in dirs:
            return {"ok": False, "error": f"not registered: {resolved}"}
        dirs.remove(resolved)

    cfg.model.extra_gguf_dirs = dirs
    try:
        dump_yaml(_require_layout().config_path, cfg)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not save config: {exc}"}
    return {"ok": True, "action": act, "path": resolved,
            "extra_gguf_dirs": dirs}
