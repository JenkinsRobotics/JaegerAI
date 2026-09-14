from __future__ import annotations

from pathlib import Path

from jaeger_whisper_stt.models import model_status, prepare_model


def test_status_finds_pywhispercpp_cache_name(tmp_path: Path, monkeypatch) -> None:
    import pywhispercpp.constants as constants

    monkeypatch.setattr(constants, "MODELS_DIR", tmp_path)
    cached = tmp_path / "ggml-base.en.bin"
    cached.write_bytes(b"weights")
    status = model_status("base.en")
    assert status.cached is True
    assert status.path == cached.resolve()
    assert status.bytes == 7


def test_prepare_load_validates_the_model_file(tmp_path: Path, monkeypatch) -> None:
    import pywhispercpp.model as model_module

    cached = tmp_path / "ggml-base.en.bin"
    cached.write_bytes(b"x" * 1_000_001)

    class FakeModel:
        def __init__(self, _name, **_kwargs) -> None:
            self.model_path = str(cached)

    monkeypatch.setattr(model_module, "Model", FakeModel)
    status = prepare_model("base.en")
    assert status.cached is True
    assert status.bytes == 1_000_001
