"""jaeger_os.core.instance.setting_meta — ``_setting()``, standalone.

Split out of ``schemas.py`` at 0.8 M1 so an engine-module's own config
slice (e.g. ``jaeger_os/nodes/kokoro_tts/config.py``) can carry catalog
metadata WITHOUT importing ``schemas.py`` — and so ``schemas.py``, in
turn, can import a module's config class to nest it into ``Config``
without a two-file circular import (``schemas`` -> module ->
``schemas``). This file has zero ``jaeger_os`` dependencies, so it can
sit on either side of that edge safely.

``schemas.py`` re-exports :func:`_setting` from here (``from
.setting_meta import _setting``) so every existing call site inside it
is unchanged; new engine-modules import it from here directly.
"""

from __future__ import annotations

from typing import Any


def _setting(group: str, *, restart: bool = False,
             advanced: bool = False) -> dict[str, Any]:
    """Settings-catalog metadata for a Config leaf field.

    The single-source settings surface (``core/settings/catalog.py``) walks
    ``Config`` and emits a descriptor for every leaf field carrying this
    metadata — CLI (``jaeger settings``) and the Swift app both render from
    that one catalog, so a setting is defined ONCE, here, and nowhere else.

      group     which settings page the field belongs to (model / display /
                voice / tts / autonomy / permissions / retention / interaction
                / kokoro_tts / ...an engine-module's own group).
      restart   True if the change only takes effect after the agent reboots
                (surfaces show a "restart required" badge).
      advanced  True to tuck the field behind the "Advanced" disclosure.

    A leaf WITHOUT this metadata is deliberately NOT exposed in the catalog
    (identity keys, provenance, and the deferred hardware/avatar/plugin
    blocks stay out until their own Phase-3 providers land)."""
    return {"group": group, "restart": restart, "advanced": advanced}


__all__ = ["_setting"]
