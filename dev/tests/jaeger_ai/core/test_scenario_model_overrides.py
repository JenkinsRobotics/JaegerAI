from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import yaml


_SCRIPT = Path(__file__).parents[3] / "benchmark" / "scenarios.py"
_SPEC = importlib.util.spec_from_file_location("jaeger_scenario_runner", _SCRIPT)
assert _SPEC and _SPEC.loader
_RUNNER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _RUNNER
_SPEC.loader.exec_module(_RUNNER)


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({
            "model": {"backend": "llama_cpp_python", "model_path": "old.gguf"},
            "external_model": {"enabled": True, "provider": "openai"},
        }),
        encoding="utf-8",
    )
    return path


def test_direct_mlx_directory_selects_mlx_and_disables_provider(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    checkpoint = tmp_path / "qwen-mlx"
    checkpoint.mkdir()

    _RUNNER._override_model_path(cfg, str(checkpoint))

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["model"]["backend"] == "mlx_lm"
    assert data["model"]["model_path"] == str(checkpoint)
    assert data["external_model"]["enabled"] is False


def test_ollama_override_is_local_and_preserves_direct_model(tmp_path: Path) -> None:
    cfg = _config(tmp_path)

    _RUNNER._override_provider(
        cfg,
        provider="ollama",
        model="qwen3.6:35b-mlx",
        base_url=None,
        ctx=65_536,
    )

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["external_model"] == {
        "enabled": True,
        "provider": "ollama",
        "model": "qwen3.6:35b-mlx",
        "ctx": 65_536,
        "base_url": "http://localhost:11434/v1",
    }
    assert data["model"]["model_path"] == "old.gguf"


def test_cloud_provider_override_remains_supported(tmp_path: Path) -> None:
    cfg = _config(tmp_path)

    _RUNNER._override_provider(
        cfg,
        provider="openai",
        model="cloud-model",
        base_url="https://example.invalid/v1",
        ctx=128_000,
    )

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["external_model"]["enabled"] is True
    assert data["external_model"]["provider"] == "openai"
    assert data["external_model"]["base_url"] == "https://example.invalid/v1"
    assert data["external_model"]["ctx"] == 128_000
