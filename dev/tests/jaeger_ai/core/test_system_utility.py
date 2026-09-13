from __future__ import annotations

from pathlib import Path

from jaeger_ai.core.models import system_utility as utility
from jaeger_ai.core.models.model_resolver import MODEL_REGISTRY


def test_system_model_is_pinned_and_not_an_agent_role():
    row = MODEL_REGISTRY[utility.SYSTEM_MODEL_KEY]
    assert row["role"] == "system"
    assert row["license"] == "Apache-2.0"
    assert len(row["sha256"]) == 64


def test_explicit_bundled_path_wins(monkeypatch, tmp_path):
    model = tmp_path / "system.gguf"
    model.write_bytes(b"gguf")
    monkeypatch.setenv(utility.SYSTEM_MODEL_ENV, str(model))
    assert utility.system_model_path() == model.resolve()


def test_missing_explicit_bundle_is_never_downloaded(monkeypatch, tmp_path):
    missing = tmp_path / "missing.gguf"
    monkeypatch.setenv(utility.SYSTEM_MODEL_ENV, str(missing))
    try:
        utility.system_model_path()
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing bundled model was accepted")


def test_guide_falls_back_to_verified_copy_when_inference_fails(monkeypatch):
    model = utility.SystemUtilityModel(Path("/missing.gguf"))
    monkeypatch.setattr(model, "respond", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    text = model.onboarding_guide("model", {"host_memory_gb": 32})
    assert "accept the recommendation" in text.lower()
    assert "manual" in text.lower()


def test_thinking_and_markdown_are_removed_from_spoken_output():
    assert utility._plain("<think>secret</think> **Use** `local` model") == "Use local model"
