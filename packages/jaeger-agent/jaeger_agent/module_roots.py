"""JaegerOS entry-point contribution for this package's module manifest."""

from __future__ import annotations

from pathlib import Path


def roots() -> tuple[Path, ...]:
    return (Path(__file__).resolve().parent,)


__all__ = ["roots"]

