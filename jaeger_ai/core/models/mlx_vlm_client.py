"""Backward-compatibility shim for MLX-VLM client.

Unified directly under `jaeger_ai.core.models.mlx_client`.
"""

from __future__ import annotations

from jaeger_ai.core.models.mlx_client import MlxVlmClient, _ChatResult

__all__ = [
    "MlxVlmClient",
]
