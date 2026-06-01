"""Recently-used external models, per provider.

The ``/model`` picker pre-populates each cloud provider's sub-menu with
the models the user has actually switched to before — so a one-off paste
of ``qwen3.5:397b`` becomes a one-click pick next time. Persisted to
``<instance>/memory/external_model_history.json`` so it survives a
restart.

Tiny on purpose — recency-ordered list per provider, capped to a small
N. Mirrors how Hermes seeds its provider sub-pickers from disk caches.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HISTORY_FILE = "external_model_history.json"
_MAX_PER_PROVIDER = 8


def _history_path(layout: Any) -> Path:
    return Path(getattr(layout, "memory_dir", ".")) / _HISTORY_FILE


def load_history(layout: Any) -> dict[str, list[str]]:
    """The full ``{provider: [model, …]}`` map, most-recent first.
    Empty dict on missing file / parse failure (never raises)."""
    path = _history_path(layout)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): [str(m) for m in v if isinstance(m, str) and m]
        for k, v in raw.items() if isinstance(v, list)
    }


def recent_models(layout: Any, provider: str, *, limit: int = 5) -> list[str]:
    """The N most recently-used models for ``provider`` (newest first)."""
    return load_history(layout).get(provider, [])[: max(0, int(limit))]


def record_use(layout: Any, provider: str, model: str) -> None:
    """Push ``model`` to the front of ``provider``'s recent list. Dedupes
    against existing entries and caps to ``_MAX_PER_PROVIDER``.
    Best-effort — a write failure is swallowed so it never breaks a switch."""
    if not provider or not model:
        return
    history = load_history(layout)
    bucket = [m for m in history.get(provider, []) if m != model]
    bucket.insert(0, model)
    history[provider] = bucket[:_MAX_PER_PROVIDER]
    try:
        path = _history_path(layout)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(history, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
