"""jaeger_os.nodes.vision — the vision node package.

Per-subsystem layout matching ``jaeger_os/nodes/whisper_stt/`` +
``jaeger_os/nodes/kokoro_tts/``.

JROS philosophy on vision (operator-locked 2026-06-06):

* The library stays universal.  JROS provides the node + a
  :class:`CameraAdapter` Protocol + generic adapters
  (:class:`USBCameraAdapter`, :class:`TCPCameraAdapter`).
* Hardware-specific wire formats (JP01-VCC01's Jetson protocol,
  vendor-specific MIPI adapters, RTSP streams from IP cameras)
  land at INSTANCE level when the operator wires their actual
  hardware.  The library doesn't ship JP01-only code paths.
* No inference (YOLO, Moondream, etc.) lives in this package.
  Inference is a SEPARATE downstream node that subscribes to
  ``/sense/camera_frame`` and publishes ``/sense/vision_analysis``.
  This
  package is the eyes; the brain (or future inference nodes) is
  what interprets what those eyes see.
"""

from .adapters import (
    CameraAdapter,
    TCPCameraAdapter,
    USBCameraAdapter,
)
from .node import VisionNode

__all__ = [
    "VisionNode",
    "CameraAdapter",
    "USBCameraAdapter",
    "TCPCameraAdapter",
]
