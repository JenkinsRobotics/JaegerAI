"""capability.py — hardware package/capability contract types.

Lives in ``jaeger_os.contract`` (0.9 contract package): a ``topology.yaml``
describes a robot in terms of these msgspec.Struct shapes, and any hardware
package loader (JROS's own ``jaeger_os.hardware.package``, or an
out-of-tree body repo) validates against them. Pure types — no loader
logic, no I/O, no jaeger_os imports beyond stdlib/msgspec. The loader
(``jaeger_os.hardware.package.load_package`` and friends) stays in
``hardware/`` and imports these types.
"""

from __future__ import annotations

from typing import Any

import msgspec


class RelaySpec(msgspec.Struct, forbid_unknown_fields=True):
    """Optional fallback path (the CC01 serial-over-ZMQ relay)."""
    transport: str
    endpoint: str = ""
    target: str = ""


class LinkSpec(msgspec.Struct, forbid_unknown_fields=True):
    transport: str                      # serial | zmq_req | mock
    protocol: str = "ascii_bracket"
    port: str = ""
    baud: int = 115200
    endpoint: str = ""
    target: str = ""
    relay: RelaySpec | None = None


class ControllerSpec(msgspec.Struct, forbid_unknown_fields=True):
    node: str                           # generic node kind (motor/light/vision)
    adapter: str                        # "pkg.adapters.mod:ClassName"
    link: LinkSpec
    enabled: bool = True
    simulated: bool = False
    heartbeat_expect_s: float = 0.0     # 0 = firmware doesn't heartbeat
    streams: dict[str, Any] = {}        # high-rate endpoints (bus-native, not Link)


class CapabilitySpec(msgspec.Struct, forbid_unknown_fields=True):
    name: str                           # "motion.move_joints" (subsystem.action)
    controller: str                     # key into controllers (or "*")
    schema: str                         # "pkg.capabilities:ArgsModel"
    handler: str = ""                   # "pkg.capabilities:fn" — empty = the
    #                                     convention: schema module + action name
    tier: str = "HARDWARE"              # permission tier label (fail-safe default)
    description: str = ""
    allow_when_latched: bool = False    # motion.stop sets this — it IS the stop


class SafetySpec(msgspec.Struct, forbid_unknown_fields=True):
    estop_scope: list[str] = []
    firmware_watchdog_required: bool = False


class PackageSpec(msgspec.Struct, forbid_unknown_fields=True):
    package: str
    requires_framework: str = ""
    display_name: str = ""
    controllers: dict[str, ControllerSpec] = {}
    capabilities: list[CapabilitySpec] = []
    safety: SafetySpec | None = None


__all__ = [
    "RelaySpec", "LinkSpec", "ControllerSpec", "CapabilitySpec",
    "SafetySpec", "PackageSpec",
]
