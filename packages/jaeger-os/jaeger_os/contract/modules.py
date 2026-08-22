"""modules.py — engine-module contract type.

Lives in ``jaeger_os.contract`` (0.9 contract package): ``ModuleSpec`` is the
validated shape of a ``module.yaml`` (slot, factory, topics, tools,
requirements). Pure type — no discovery/loading logic, no jaeger_os
imports beyond stdlib/msgspec. The loader (``jaeger_os.core.modules`` —
``load_module``, ``discover_modules``, ``NODES_DIR``/``PLUGINS_DIR``) stays
in ``core/`` and imports this type.
"""

from __future__ import annotations

import msgspec


class ModuleSpec(msgspec.Struct, forbid_unknown_fields=True):
    module: str
    slot: str
    factory: str
    version: str = ""
    consumes: list[str] = []
    produces: list[str] = []
    tools: list[str] = []
    config: str = ""
    requires_libraries: list[str] = []
    # Host-platform gate (module.yaml's analogue of a plugin manifest's
    # ``requires: platform:``) — empty means "any platform". 0.8 M3b:
    # imessage is darwin-only; strict like requires_libraries, no
    # silent default beyond "unset = unrestricted".
    requires_platform: list[str] = []


__all__ = ["ModuleSpec"]
