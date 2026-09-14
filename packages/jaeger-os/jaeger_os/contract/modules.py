"""modules.py — engine-module contract type.

Lives in ``jaeger_os.contract`` (0.9 contract package): ``ModuleSpec`` is the
validated shape of a ``module.yaml`` (identity, implementation, slot,
factory, topics, tools, requirements). Pure type — no discovery/loading
logic, no jaeger_os
imports beyond stdlib/msgspec. The loader (``jaeger_os.core.modules`` —
``load_module``, ``discover_modules``, ``NODES_DIR``/``PLUGINS_DIR``) stays
in ``core/`` and imports this type.
"""

from __future__ import annotations

from typing import Any

import msgspec


class ModuleSpec(msgspec.Struct, forbid_unknown_fields=True):
    module: str
    slot: str
    factory: str
    # Globally stable identity. ``module`` above is the short runtime name;
    # ``id`` is what registries, diagnostics, and documentation can carry
    # without colliding with another publisher's module of the same name.
    # Older manifests omit the identity block and remain valid.
    id: str = ""
    name: str = ""
    type: str = "module"
    implementation: str = ""
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
    # The OWNERSHIP axis (Jaeger-Template's TAXONOMY.md, "Module KINDS")
    # — orthogonal to ``slot``. ``slot`` says what ROLE a module fills;
    # ``kind`` says what it is ALLOWED TO TOUCH:
    #
    #   driver      owns ONE hardware device family, exclusively.
    #               Nothing outside a driver-kind module may open a
    #               device.
    #   processing  software-only, universal by construction — touches
    #               topics, never devices (a codec, an image op, a VAD).
    #   engine      fills a capability slot (tts, stt, animation, ...).
    #   mind        the agent itself — singleton, slot ``mind``.
    #
    # Empty means "unclassified", so every module.yaml written before
    # this field existed keeps validating. The taxonomy was documented
    # in the template and unrepresentable in the schema, which meant the
    # driver-exclusivity rule could only ever be enforced against a
    # comment. Declaring it is step one; enforcement is a later,
    # separate decision.
    kind: str = ""

    # ── set by discovery, not by module.yaml ──────────────────────
    # Where this module was found, and whether it came from the
    # project's own modules/ directory rather than an installed
    # package. An operator asking "which copy am I actually running?"
    # should not have to reason about sys.path to find out.
    source_dir: Any = None
    local: bool = False


#: The legal values for ``ModuleSpec.kind``. Validated at load time
#: rather than by the type system: msgspec would reject an unknown enum
#: with a decode error that doesn't name the offending file.
MODULE_KINDS: frozenset[str] = frozenset(
    {"driver", "processing", "engine", "mind"}
)


__all__ = ["ModuleSpec", "MODULE_KINDS"]
