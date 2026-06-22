"""``jaeger_os.hardware`` — the hardware-integration framework.

Design: dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md (operator-approved
2026-06-12). This package is plan §4.2 step 1+2: the framework plus
the simulated JP01 package. No Tier-3 supervisor lives here — node
process lifecycle belongs to the daemon-arch plan; everything in this
package is supervisable but not self-supervising.

Layering (each boundary keeps its existing JROS idiom):

    agent tool boundary    Pydantic   (ToolDef.args_model)
    bus boundary           msgspec    (jaeger_os.topics structs)
    wire boundary          Protocol   (bytes — package-owned)

Public surface:

  * ``Transport`` / ``SerialTransport`` / ``ZmqReqTransport`` /
    ``MockTransport`` — byte channels with the SerialHandler-shaped
    lifecycle (connect/disconnect/is_connected/write/read).
  * ``Protocol`` / ``AsciiBracketProtocol`` / ``JsonLineProtocol`` —
    framing + encoding, a separate axis from transport (JP01's
    dual-path proves the same brackets ride serial OR a ZMQ relay).
  * ``Link`` — Transport × Protocol composition with the optional
    relay fallback and an RX reader thread.
  * ``load_package`` / ``PackageSpec`` — topology.yaml → validated
    robot description.
  * ``register_package_capabilities`` — capability declarations →
    ordinary JROS agent tools (beta-gated, tiered, health-bound).
  * ``EStopLatch`` — the L2 system e-stop latch.

``FRAMEWORK_VERSION`` is what a package's ``requires_framework``
constraint is checked against.
"""

from __future__ import annotations

from .boot import boot_hardware, shutdown_hardware
from .capabilities import register_package_capabilities
from .link import Link
from .package import PackageSpec, load_package
from .protocol import AsciiBracketProtocol, JsonLineProtocol, Protocol
from .safety import EStopLatch
from .transport import (
    MockTransport,
    SerialTransport,
    Transport,
    ZmqReqTransport,
)

# What a package's ``requires_framework: >=X.Y`` constraint checks
# against (package.py reads it lazily to avoid an import cycle).
FRAMEWORK_VERSION = "0.6.0"

__all__ = [
    "FRAMEWORK_VERSION",
    "Transport", "SerialTransport", "ZmqReqTransport", "MockTransport",
    "Protocol", "AsciiBracketProtocol", "JsonLineProtocol",
    "Link",
    "PackageSpec", "load_package",
    "register_package_capabilities",
    "EStopLatch",
    "boot_hardware", "shutdown_hardware",
]
