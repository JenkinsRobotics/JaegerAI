"""Dynamic conversation model selection shim.

For full routing and gating logic, see :mod:`jaeger_ai.core.models.router`.
"""

from __future__ import annotations

from jaeger_ai.core.models.router import select_client

__all__ = [
    "select_client",
]
