"""node.py — VisionNode.

Wraps a :class:`CameraAdapter` and publishes :class:`CameraFrame`
messages on ``/sense/vision`` at whatever rate the adapter
produces frames.  The node itself is hardware-agnostic — the
adapter handles the actual capture (USB / TCP / future modes).

Symmetric in shape with :class:`STTNode`: a polling source node
that owns the hardware adapter, runs the adapter's loop on its
own ``tick()``, and publishes typed messages to the bus.

Threading
---------
The adapter's ``next_frame()`` MAY block up to its own internal
timeout (default 1 s).  ``tick()`` polls with a short timeout so
``stop()`` stays responsive.  Inference / analysis nodes that
subscribe to ``/sense/vision`` are responsible for not falling
behind — backpressure here is the Bus's queue, not the camera.
"""

from __future__ import annotations

from typing import Any

from jaeger_os import topics
from jaeger_os.nodes.base import Node
from jaeger_os.nodes.vision.adapters import CameraAdapter, FrameEnvelope
from jaeger_os.transport import Bus


class VisionNode(Node):
    """Poll a :class:`CameraAdapter` for frames; publish
    :class:`CameraFrame` on ``/sense/vision``.

    The adapter is dependency-injected — production callers pass
    :class:`USBCameraAdapter` or :class:`TCPCameraAdapter`; tests
    pass a mock that returns canned frames.  Same Protocol-based
    design as the STT node uses for WhisperSTTContinuous.
    """

    def __init__(
        self,
        *,
        bus: Bus,
        adapter: CameraAdapter,
        name: str = "vision",
        camera_id: str = "default",
        poll_timeout_s: float = 0.1,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self.adapter = adapter
        self.camera_id = camera_id
        self._poll_timeout_s = poll_timeout_s
        self._frame_seq = 0

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        self.adapter.start()
        self._log(f"adapter started; will publish {topics.SENSE_VISION}")

    def tick(self) -> None:
        frame = self.adapter.next_frame(timeout=self._poll_timeout_s)
        if frame is None:
            return
        self._publish(frame)

    def teardown(self) -> None:
        try:
            self.adapter.stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"adapter stop error: {type(exc).__name__}: {exc}")

    # ── publish helper ───────────────────────────────────────────

    def _publish(self, frame: FrameEnvelope) -> None:
        self._frame_seq += 1
        self.bus.publish(topics.CameraFrame(
            image_w=frame.width,
            image_h=frame.height,
            encoding=frame.encoding,
            frame_bytes=frame.data,
            camera_id=self.camera_id,
            frame_seq=self._frame_seq,
            node_id=self.name,
        ))
