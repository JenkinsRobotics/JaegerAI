"""Backward-compatibility shim for recently-used external models.

Unified directly under `jaeger_ai.core.models.external_model`.
"""

from __future__ import annotations

from jaeger_ai.core.models import external_model as _em

_HISTORY_FILE = _em._HISTORY_FILE
_MAX_PER_PROVIDER = _em._MAX_PER_PROVIDER
_history_path = _em._history_path
load_history = _em.load_history
recent_models = _em.recent_models
record_use = _em.record_use

__all__ = [
    "load_history",
    "recent_models",
    "record_use",
]
