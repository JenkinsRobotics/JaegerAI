"""ContextVar-scoped runtime model overlay for A/B evals, cost tiering & replay.

Adapted from CrewAI (MIT License) ``llm_overlay.py`` pattern — zero global
mutation, thread- and asyncio-task-safe via ``contextvars.ContextVar``.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Any, Iterator, Mapping

_model_overlay_var: ContextVar[dict[str, Any]] = ContextVar("jaeger_model_overlay", default={})


def current_model_overlay() -> dict[str, Any]:
    return dict(_model_overlay_var.get())


def resolve_overlaid_model(model_id: str, *, role: str | None = None) -> Any:
    """Resolve an active overlay for ``role`` or ``model_id`` (falls back to ``model_id``)."""
    overlay = _model_overlay_var.get()
    if not overlay:
        return model_id
    if role and f"role:{role}" in overlay:
        return overlay[f"role:{role}"]
    if model_id in overlay:
        return overlay[model_id]
    if f"model:{model_id}" in overlay:
        return overlay[f"model:{model_id}"]
    if "model:*" in overlay:
        return overlay["model:*"]
    return model_id


@contextlib.contextmanager
def model_overlay(overrides: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Temporarily override model resolution inside this context/task."""
    merged = {**_model_overlay_var.get(), **dict(overrides)}
    token = _model_overlay_var.set(merged)
    try:
        yield merged
    finally:
        _model_overlay_var.reset(token)


__all__ = ["current_model_overlay", "model_overlay", "resolve_overlaid_model"]
