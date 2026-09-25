"""ports.py — named port constants (the 0.9 contract package).

One place for every port number JROS or a JP01-class body wires up, so a
number typed twice (once in this repo, once in JP01_Firmware) can't drift
silently. See ``contract/README.md`` for the cross-repo duplication this
package exists to retire.

Two families today:

* **Animation bridge** — the local WebSocket the animation/animation_dev
  node's ``FrameBridge`` serves, and the Swift/PySide6 avatar surfaces
  connect to. Same-machine only (``127.0.0.1``), not part of the JP01 wire.
* **JP01 VCC01** — the Jetson vision computer's real measured ports
  (survey 2026-06-12, JP01_Firmware branch 2.0; see
  ``jaeger_os/hardware/packages/jp01/topology.yaml``). These are declared
  as YAML data in this repo already (one copy here) — the constants exist
  so JP01_Firmware's OWN code (a separate repo) has something to import or
  vendor instead of re-typing the numbers.
"""

from __future__ import annotations

# ── animation bridge (local WebSocket, avatar frame streaming) ──────────

ANIMATION_BRIDGE_HOST = "127.0.0.1"
ANIMATION_BRIDGE_DEFAULT_PORT = 8765

# ── JP01 — VCC01 (Jetson vision computer) ────────────────────────────────
# Real measured values; topology.yaml is this repo's source of truth for
# actual wiring, these constants are for JP01_Firmware-side de-duplication.

JP01_VCC01_CMD_PORT = 5556                    # ZMQ REP command channel
JP01_VCC01_TELEMETRY_PORT = 5555              # ZMQ PUB telemetry
JP01_VCC01_VISION_TELEMETRY_PORT = 5558       # ZMQ PUB vision telemetry
JP01_VCC01_VIDEO_UDP_PORTS = (5001, 5003)     # UDP video stream (2 ports)

# Real measured values, added 4.0 P1 (JP01_Firmware branch 4.0 survey):
# confirmed against VCC01 core/network_zmq.py (CommsServer.__init__
# defaults) and core/audio_manager.py (AUDIO_MIC_PORT/AUDIO_SPK_PORT env
# defaults). These are the "5560/557x" ports this repo's contract/README.md
# previously flagged as grepped-for-but-not-found.
JP01_VCC01_VISION_REP_PORT = 5560             # ZMQ REP vision-stream commands
JP01_VCC01_AUDIO_MIC_UDP_PORT = 5570          # raw UDP: Jetson mic  -> Mac
JP01_VCC01_AUDIO_SPK_UDP_PORT = 5571          # raw UDP: Mac -> Jetson speaker

__all__ = [
    "ANIMATION_BRIDGE_HOST",
    "ANIMATION_BRIDGE_DEFAULT_PORT",
    "JP01_VCC01_CMD_PORT",
    "JP01_VCC01_TELEMETRY_PORT",
    "JP01_VCC01_VISION_TELEMETRY_PORT",
    "JP01_VCC01_VIDEO_UDP_PORTS",
    "JP01_VCC01_VISION_REP_PORT",
    "JP01_VCC01_AUDIO_MIC_UDP_PORT",
    "JP01_VCC01_AUDIO_SPK_UDP_PORT",
]
