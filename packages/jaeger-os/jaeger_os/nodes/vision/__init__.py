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
  ``/sense/camera/image_raw`` and publishes ``/sense/vision/analysis``.
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
    "make_vision_node",
]


def make_vision_node(bus, config=None):
    """Chassis-contract factory ``(bus, config) -> VisionNode``.

    The same shape ``jaeger_os.nodes.audio_io:make_audio_io_node`` has,
    and for the same reason: a manifest can only name a node by a
    ``(bus, config)`` callable, and ``VisionNode`` takes a constructed
    ``adapter=`` that an app has no business building itself. Choosing
    between the generic adapters from a config table is exactly the
    "which device?" question a manifest exists to answer.

    ``source``:
      ``"usb"``  a local camera by ``device_index`` (OpenCV)
      ``"tcp"``  frames pushed by a remote board to ``host``/``port``

    Hardware-specific wire formats stay out of here, per this package's
    docstring — an instance that needs one subclasses ``CameraAdapter``
    and names its own factory instead.
    """
    cfg = dict(config or {})
    source = str(cfg.get("source", "usb")).lower()
    encoding = str(cfg.get("encoding", "jpeg"))

    if source == "usb":
        adapter = USBCameraAdapter(
            device_index=int(cfg.get("device_index", 0)),
            encoding=encoding,
            target_fps=float(cfg.get("target_fps", 10.0)),
            jpeg_quality=int(cfg.get("jpeg_quality", 80)),
        )
    elif source == "tcp":
        adapter = TCPCameraAdapter(
            host=str(cfg.get("host", "127.0.0.1")),
            port=int(cfg.get("port", 9001)),
            encoding=encoding,
            connect_timeout_s=float(cfg.get("connect_timeout_s", 5.0)),
            recv_timeout_s=float(cfg.get("recv_timeout_s", 1.0)),
        )
    else:
        # Loudly, like the STT method registry: booting the wrong source
        # after a typo makes a camera that sees nothing look like a
        # camera that is merely unplugged.
        raise ValueError(
            f"vision: unknown source {source!r}; choose one of: usb, tcp")

    return VisionNode(
        bus=bus,
        adapter=adapter,
        name=str(cfg.get("name", "vision")),
        camera_id=str(cfg.get("camera_id", "default")),
        poll_timeout_s=float(cfg.get("poll_timeout_s", 0.1)),
    )
