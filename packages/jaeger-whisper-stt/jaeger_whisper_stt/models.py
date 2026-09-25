"""Whisper model-cache preflight for repeatable robot deployments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelStatus:
    name: str
    cached: bool
    path: Path | None
    bytes: int

    def as_json(self) -> dict:
        value = asdict(self)
        value["path"] = str(self.path) if self.path else None
        return value


def cached_model_path(name: str) -> Path | None:
    """Resolve a model without downloading it."""
    direct = Path(name).expanduser()
    if direct.is_file():
        return direct.resolve()

    from pywhispercpp.constants import MODELS_DIR

    root = Path(MODELS_DIR).expanduser()
    for candidate in (
        root / name,
        root / f"{name}.bin",
        root / f"ggml-{name}.bin",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def model_status(name: str) -> ModelStatus:
    path = cached_model_path(name)
    return ModelStatus(
        name=name,
        cached=path is not None,
        path=path,
        bytes=path.stat().st_size if path else 0,
    )


def prepare_model(name: str) -> ModelStatus:
    """Download if needed and load once to validate the cached weights."""
    from pywhispercpp.model import Model

    model = Model(
        name, print_realtime=False, print_progress=False,
        single_segment=True, no_context=True,
    )
    path = Path(model.model_path).resolve()
    size = path.stat().st_size
    if size < 1_000_000:
        raise RuntimeError(f"model cache file is unexpectedly small: {path}")
    return ModelStatus(name=name, cached=True, path=path, bytes=size)


__all__ = ["ModelStatus", "cached_model_path", "model_status", "prepare_model"]
