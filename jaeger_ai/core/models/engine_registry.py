"""Engine registry — the selectable inference engines + the per-format
picker that turns ``config.runtime`` into a loaded client.

This is the *selection + loader* layer that sits on top of the read-only
inventory in :mod:`jaeger_os.core.models.runtimes`. Where ``runtimes.py``
answers "what engines are installed?" (the ``/runtime`` panel), this
module answers "given THIS model, which engine loads it, and how?" —
mirroring LM Studio's Settings → Runtime panel where each model *format*
(GGUF, MLX) maps to a chosen *engine*:

    GGUF  →  Metal llama.cpp   (llama-cpp-python, in-process)
    MLX   →  Apple MLX         (mlx-lm  — text · mlx-vlm — multimodal)

Two axes, kept deliberately separate so the picker stays simple:

  • **format**  — derived from the model on disk (a ``.gguf`` *file* vs an
    MLX *directory*). Not user-chosen; it's a fact about the weights.
  • **engine**  — chosen by the operator per format (the dropdown), or
    ``"auto"`` to let :func:`default_engine_for_format` decide.

Engines are described by :class:`EngineSpec` (id, label, the formats it
loads, an availability probe, and a lazy ``loader``). The loaders import
their heavy deps *inside* the call so importing this module never drags
in ``llama_cpp`` / ``mlx`` — it stays cheap on any host.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ── Format detection ────────────────────────────────────────────────


def detect_format(model_path: str | Path) -> str:
    """Classify a model reference as ``"gguf"`` or ``"mlx"``.

    MLX models are *directories* (config.json + *.safetensors shards);
    GGUF models are single ``.gguf`` *files*. A bare registry key or
    name with no path separator defaults to ``"gguf"`` — the default
    local format — so ``resolve_engine("gemma-4-12b-it-q4_k_m", …)``
    still picks the llama.cpp engine.
    """
    p = Path(str(model_path)).expanduser()
    if p.is_dir():
        return "mlx"
    if str(p).lower().endswith(".gguf"):
        return "gguf"
    # Not on disk yet (registry key / bare name): infer from the suffix,
    # else assume GGUF (Jaeger's default local format).
    return "mlx" if p.suffix == "" and "mlx" in p.name.lower() else "gguf"


def _read_mlx_config(model_dir: str | Path) -> dict[str, Any]:
    """Best-effort read of an MLX model's ``config.json`` — {} on any
    failure (missing file, bad JSON, not a dir)."""
    try:
        cfg_path = Path(str(model_dir)).expanduser() / "config.json"
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mlx_needs_vlm(model_dir: str | Path) -> bool:
    """True when an MLX model can only be loaded by ``mlx-vlm`` (the
    multimodal loader), not the text-only ``mlx-lm``.

    The reliable tell is the ``model_type``: the ``*_unified`` variants
    (e.g. ``gemma4_unified``) aren't registered in ``mlx-lm`` at all.
    A plain multimodal config (``vision_config`` present) is NOT a
    reliable signal on its own — some multimodal builds (the 26B-A4B)
    still load fine through ``mlx-lm`` — so we only force ``mlx-vlm``
    for the model types ``mlx-lm`` provably rejects.
    """
    cfg = _read_mlx_config(model_dir)
    model_type = str(cfg.get("model_type", "")).lower()
    if model_type.endswith("_unified"):
        return True
    arches = cfg.get("architectures") or []
    return any("Unified" in str(a) for a in arches)


# ── Engine descriptors ──────────────────────────────────────────────


@dataclass(frozen=True)
class EngineSpec:
    """One selectable inference engine.

    ``loader(model_config, *, warmup)`` returns a brain client (the same
    duck-typed surface ``make_client`` returns). It imports its heavy
    dependency lazily so this module imports cleanly everywhere.
    """

    id: str                              # stable id, e.g. "mlx-lm"
    display_name: str                    # what the panel shows
    formats: tuple[str, ...]             # "gguf" / "mlx"
    description: str
    loader: Callable[..., Any] = field(repr=False)
    module: str = ""                     # import name for the version/availability probe
    install_hint: str = ""

    def version(self) -> str | None:
        """``__version__`` of the backing module, or None when absent."""
        if not self.module:
            return "installed"
        try:
            mod = __import__(self.module)
            return str(getattr(mod, "__version__", None) or "installed")
        except ImportError:
            return None
        except Exception:  # noqa: BLE001 — never propagate from a probe
            return None

    def available(self) -> bool:
        return self.version() is not None


# ── Loaders (lazy heavy imports) ────────────────────────────────────


def _load_llama_cpp(model_config: Any, *, warmup: bool = True) -> Any:
    from jaeger_ai.main import LlamaCppPythonClient
    return LlamaCppPythonClient(model_config, warmup=warmup)


def _load_mlx_lm(model_config: Any, *, warmup: bool = True) -> Any:
    from jaeger_ai.core.models.mlx_client import MlxClient
    return MlxClient(model_config.model_path, warmup=warmup)


def _load_mlx_vlm(model_config: Any, *, warmup: bool = True) -> Any:
    from jaeger_ai.core.models.mlx_vlm_client import MlxVlmClient
    return MlxVlmClient(model_config.model_path, warmup=warmup)


# ── The registry ────────────────────────────────────────────────────


_ENGINES: tuple[EngineSpec, ...] = (
    EngineSpec(
        id="llama-cpp-python",
        display_name="Metal llama.cpp",
        formats=("gguf",),
        description="GGUF, in-process, Apple Metal accelerated.",
        loader=_load_llama_cpp,
        module="llama_cpp",
        install_hint="pip install llama-cpp-python",
    ),
    EngineSpec(
        id="mlx-lm",
        display_name="Apple MLX (mlx-lm)",
        formats=("mlx",),
        description="Apple-Silicon MLX engine — text models.",
        loader=_load_mlx_lm,
        module="mlx_lm",
        install_hint="pip install mlx-lm",
    ),
    EngineSpec(
        id="mlx-vlm",
        display_name="Apple MLX (mlx-vlm)",
        formats=("mlx",),
        description="Apple-Silicon MLX engine — multimodal / unified models.",
        loader=_load_mlx_vlm,
        module="mlx_vlm",
        install_hint="pip install mlx-vlm",
    ),
)

# Per-format default engine id (used when the operator picks "auto").
_FORMAT_DEFAULTS: dict[str, str] = {
    "gguf": "llama-cpp-python",
    "mlx": "mlx-lm",
}


def all_engines() -> list[EngineSpec]:
    """Every registered in-process engine, in display order."""
    return list(_ENGINES)


def get_engine(engine_id: str) -> EngineSpec | None:
    eid = (engine_id or "").strip().lower()
    for spec in _ENGINES:
        if spec.id == eid:
            return spec
    return None


def engines_for_format(fmt: str) -> list[EngineSpec]:
    """The engines that can load a given format, in display order."""
    return [s for s in _ENGINES if fmt in s.formats]


def default_engine_for_format(fmt: str, model_path: str | Path | None = None) -> EngineSpec:
    """The engine ``"auto"`` resolves to for a format.

    For MLX this is content-aware: a ``*_unified`` model that ``mlx-lm``
    can't load resolves to ``mlx-vlm`` when that's installed. Everything
    else takes the static per-format default, falling back to the first
    *available* engine for the format if the default isn't installed.
    """
    if fmt == "mlx" and model_path is not None and mlx_needs_vlm(model_path):
        vlm = get_engine("mlx-vlm")
        if vlm is not None and vlm.available():
            return vlm
    default = get_engine(_FORMAT_DEFAULTS.get(fmt, "")) or None
    if default is not None and default.available():
        return default
    for spec in engines_for_format(fmt):
        if spec.available():
            return spec
    # Nothing installed — return the static default so the caller can
    # surface its install_hint rather than crashing on an empty list.
    return default or engines_for_format(fmt)[0]


def runtime_selection(runtime_config: Any, fmt: str) -> str:
    """Read the operator's per-format engine choice from a RuntimeConfig
    (``"auto"`` when unset or no config present)."""
    if runtime_config is None:
        return "auto"
    attr = {"gguf": "gguf_engine", "mlx": "mlx_engine"}.get(fmt)
    return (getattr(runtime_config, attr, None) or "auto") if attr else "auto"


def valid_engine_ids(fmt: str) -> set[str]:
    """The engine ids (plus ``"auto"``) accepted for a format."""
    return {"auto", *(s.id for s in engines_for_format(fmt))}


def set_runtime_engine(runtime_config: Any, fmt: str, engine_id: str) -> str:
    """Validate + apply a per-format engine selection onto a RuntimeConfig
    *in place*. Returns the normalised engine id.

    Raises ``ValueError`` when the format is unknown or the engine can't
    load that format — the single validation both the CLI and the TUI
    selector call, so the rule lives in exactly one place.
    """
    fmt = (fmt or "").strip().lower()
    attr = {"gguf": "gguf_engine", "mlx": "mlx_engine"}.get(fmt)
    if attr is None:
        raise ValueError(f"unknown format {fmt!r} (expected 'gguf' or 'mlx')")
    engine_id = (engine_id or "").strip().lower()
    if engine_id not in valid_engine_ids(fmt):
        raise ValueError(
            f"engine {engine_id!r} can't load {fmt.upper()} models; "
            f"valid: {', '.join(sorted(valid_engine_ids(fmt)))}"
        )
    setattr(runtime_config, attr, engine_id)
    return engine_id


def resolve_engine_id_for_selection(runtime_config: Any, fmt: str) -> str:
    """The engine id a format's selection points at, WITHOUT a model in
    hand — the operator's explicit choice, or the static per-format
    default when set to ``"auto"``. Used by the panel to highlight which
    engines are currently chosen."""
    sel = runtime_selection(runtime_config, fmt)
    if sel and sel != "auto":
        spec = get_engine(sel)
        if spec is not None and fmt in spec.formats:
            return spec.id
    return _FORMAT_DEFAULTS.get(fmt, "")


def resolve_engine(model_path: str | Path, runtime_config: Any = None) -> EngineSpec:
    """Pick the engine for ``model_path``: honour the operator's per-format
    selection when set and installed, else fall back to the auto default."""
    fmt = detect_format(model_path)
    selected = runtime_selection(runtime_config, fmt)
    if selected and selected != "auto":
        spec = get_engine(selected)
        if spec is not None and fmt in spec.formats and spec.available():
            return spec
        # Selection is stale/uninstalled/wrong-format — fall through to
        # auto rather than failing the boot.
    return default_engine_for_format(fmt, model_path)
