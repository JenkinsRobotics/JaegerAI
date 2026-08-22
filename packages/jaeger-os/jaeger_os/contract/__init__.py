"""jaeger_os.contract — the ONE wire truth.

The 0.9 structural work's step 1 (``dev/docs/vision/THREE_TIER_STRUCTURE.md``,
"0.9 structural work" §1): topic names/schemas, ports, packet formats, the
client protocol, and the module/capability contract types, all in one
package that imports NOTHING from the rest of ``jaeger_os`` — stdlib,
msgspec, and (for validation-facing types elsewhere) pydantic only. This is
the nervous-system rule enforced, not promised: lower layers never wait on
higher ones, and ``contract`` is the lowest layer of all.

Sub-modules:

* :mod:`jaeger_os.contract.topics` — bus topic names + msgspec schemas
  (moved from ``jaeger_os.transport.topics``, which now re-exports this
  module for its ~60 existing importers).
* :mod:`jaeger_os.contract.protocol` — the client (NDJSON) wire protocol
  frame builders/parsers (moved from ``jaeger_os.interfaces.protocol``);
  ``protocol_v1_fixtures.json`` lives alongside it.
* :mod:`jaeger_os.contract.capability` — hardware package/capability types
  (``PackageSpec`` and friends; the loader stays in
  ``jaeger_os.hardware.package``).
* :mod:`jaeger_os.contract.modules` — the engine-module type (``ModuleSpec``;
  the loader stays in ``jaeger_os.core.modules``).
* :mod:`jaeger_os.contract.ports` — named port constants.
* :mod:`jaeger_os.contract.wire` — named packet-format + audio constants.

See ``contract/README.md`` for the JP01_Firmware (out-of-tree, cross-repo)
duplication this package exists to retire.
"""

from __future__ import annotations

from . import capability, modules, ports, protocol, topics, wire

__all__ = ["topics", "protocol", "capability", "modules", "ports", "wire"]
