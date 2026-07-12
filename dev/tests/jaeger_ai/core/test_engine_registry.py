"""Engine registry + per-format runtime selection.

Covers the selection layer that turns ``config.runtime`` into a chosen
engine (the Runtime panel): format detection, the auto/multimodal
routing, the operator's manual selection, and the validation shared by
the CLI + TUI selectors.
"""

from __future__ import annotations

import json

import pytest

from jaeger_ai.core.models import engine_registry as er
from jaeger_ai.core.instance.schemas import Config, RuntimeConfig


# ── format detection ────────────────────────────────────────────────


def test_detect_format_gguf_file(tmp_path):
    f = tmp_path / "gemma-4-12B-it-Q4_K_M.gguf"
    f.write_bytes(b"\x00")
    assert er.detect_format(f) == "gguf"


def test_detect_format_mlx_directory(tmp_path):
    d = tmp_path / "gemma-4-26B-A4B-it-MLX-4bit"
    d.mkdir()
    assert er.detect_format(d) == "mlx"


def test_detect_format_bare_registry_key_defaults_gguf():
    # A registry key with no path separator / suffix is the GGUF default.
    assert er.detect_format("gemma-4-12b-it-q4_k_m") == "gguf"


# ── multimodal / unified routing ────────────────────────────────────


def _write_mlx(tmp_path, name, config):
    d = tmp_path / name
    d.mkdir()
    (d / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return d


def test_mlx_needs_vlm_for_unified(tmp_path):
    d = _write_mlx(tmp_path, "gemma-4-12B-it-8bit",
                   {"model_type": "gemma4_unified",
                    "architectures": ["Gemma4UnifiedForConditionalGeneration"]})
    assert er.mlx_needs_vlm(d) is True


def test_mlx_standard_does_not_need_vlm(tmp_path):
    # A plain multimodal config alone is NOT enough to force mlx-vlm —
    # the 26B-A4B loads fine through mlx-lm despite vision_config.
    d = _write_mlx(tmp_path, "gemma-4-26B-A4B-it-MLX-4bit",
                   {"model_type": "gemma4", "vision_config": {},
                    "architectures": ["Gemma4ForConditionalGeneration"]})
    assert er.mlx_needs_vlm(d) is False


# ── registry shape ──────────────────────────────────────────────────


def test_registry_lists_three_engines():
    ids = {e.id for e in er.all_engines()}
    assert {"llama-cpp-python", "mlx-lm", "mlx-vlm"} <= ids


def test_engines_for_format_partitions_by_format():
    assert [e.id for e in er.engines_for_format("gguf")] == ["llama-cpp-python"]
    assert {e.id for e in er.engines_for_format("mlx")} == {"mlx-lm", "mlx-vlm"}


def test_llama_cpp_is_available():
    # The GGUF engine is always present in the JROS venv.
    assert er.get_engine("llama-cpp-python").available() is True


# ── resolution / selection ──────────────────────────────────────────


def test_resolve_gguf_auto_picks_llama_cpp(tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(b"\x00")
    assert er.resolve_engine(f, RuntimeConfig()).id == "llama-cpp-python"


def test_manual_selection_honoured_when_available(tmp_path):
    d = _write_mlx(tmp_path, "m-mlx", {"model_type": "gemma4"})
    rc = RuntimeConfig(mlx_engine="mlx-lm")
    assert er.resolve_engine(d, rc).id == "mlx-lm"


def test_stale_selection_falls_back_to_auto(tmp_path):
    # Selecting an uninstalled engine must not break boot — fall back.
    d = _write_mlx(tmp_path, "m-unified", {"model_type": "gemma4_unified"})
    rc = RuntimeConfig(mlx_engine="mlx-vlm")
    resolved = er.resolve_engine(d, rc)
    # mlx-vlm may or may not be installed; either way resolution succeeds
    # and returns an mlx-capable engine, never raising.
    assert "mlx" in resolved.formats


# ── set_runtime_engine validation (shared by CLI + TUI) ─────────────


def test_set_runtime_engine_applies():
    rc = RuntimeConfig()
    assert er.set_runtime_engine(rc, "mlx", "mlx-vlm") == "mlx-vlm"
    assert rc.mlx_engine == "mlx-vlm"


def test_set_runtime_engine_rejects_wrong_format():
    rc = RuntimeConfig()
    with pytest.raises(ValueError):
        er.set_runtime_engine(rc, "gguf", "mlx-lm")


def test_set_runtime_engine_rejects_unknown_format():
    with pytest.raises(ValueError):
        er.set_runtime_engine(RuntimeConfig(), "onnx", "auto")


def test_auto_is_always_valid():
    rc = RuntimeConfig(gguf_engine="llama-cpp-python")
    assert er.set_runtime_engine(rc, "gguf", "auto") == "auto"
    assert rc.gguf_engine == "auto"


# ── Config integration ──────────────────────────────────────────────


def test_runtime_config_defaults_to_auto():
    rc = RuntimeConfig()
    assert rc.gguf_engine == "auto"
    assert rc.mlx_engine == "auto"


def test_config_without_runtime_block_defaults(tmp_path):
    # An existing config.yaml predating the runtime block still loads.
    cfg = Config.model_validate({
        "instance_name": "t",
        "model": {"model_path": "gemma-4-12b-it-q4_k_m"},
    })
    assert cfg.runtime.gguf_engine == "auto"
    assert cfg.runtime.mlx_engine == "auto"
