"""Metadata helper for Pydantic config schemas."""

from __future__ import annotations

from typing import Any


def _setting(
    group: str,
    *,
    restart: bool = False,
    advanced: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Helper to attach schema metadata to configuration fields."""
    return {
        "group": group,
        "restart": restart,
        "advanced": advanced,
        **kwargs,
    }
