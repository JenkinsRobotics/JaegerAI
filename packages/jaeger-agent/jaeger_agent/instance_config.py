"""Cached read of the instance ``config.yaml``.

The ported hooks and checkpoint layers both consult config on the tool-call
hot path — ``shell_hooks.fire`` runs before *every* tool call. Parsing YAML
and re-validating a large Pydantic model that often would be a real cost for
a feature that is off by default, so this caches on the file's mtime+size,
matching the donor's note that its own ``load_config`` "has mtime-based
caching, so this adds negligible overhead".

Deliberately tiny and dependency-light: it must be importable from
``jaeger_agent`` without dragging in the product layer at import time.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, tuple[tuple[float, int], Any]] = {}


def _stamp(path: Path) -> tuple[float, int] | None:
    try:
        st = path.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def load(layout: Any = None) -> Any | None:
    """The instance ``Config``, or None when unreadable.

    Never raises: callers are gates that must fail closed to "feature off"
    rather than take down the tool call they are wrapped around.
    """
    try:
        if layout is None:
            from jaeger_agent.workspace import get_layout
            layout = get_layout()
        path = Path(layout.config_path)
    except Exception:
        return None

    stamp = _stamp(path)
    if stamp is None:
        return None
    key = str(path)

    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]

    try:
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        cfg = load_yaml(path, Config)
    except Exception as exc:
        logger.debug("instance_config: load failed (%s)", exc)
        return None

    with _lock:
        _cache[key] = (stamp, cfg)
    return cfg


def section(name: str, layout: Any = None) -> Any | None:
    """One top-level config section (e.g. ``"hooks"``), or None."""
    cfg = load(layout)
    return getattr(cfg, name, None) if cfg is not None else None


def clear_cache() -> None:
    """Test seam / explicit invalidation after a config write."""
    with _lock:
        _cache.clear()


__all__ = ["clear_cache", "load", "section"]
