"""jaeger_os.nodes — Node base class + the per-subsystem node
implementations that land at Track B onwards.

A :class:`~jaeger_os.nodes.base.Node` is a long-lived unit of work
that:

  * Owns a transport (a :class:`~jaeger_os.transport.Bus`).
  * Has a name / id used for log routing and topic envelopes.
  * Runs through a four-phase lifecycle: ``setup`` → ``tick``
    (loop) → ``teardown`` → ``health()``.
  * Handles signals: graceful SIGTERM, restart-on-SIGUSR1.

In monolithic mode (``./launch``, default) every node lives in the
same Python process and shares one :class:`InProcBus`.  In
multiprocess mode (``./launch --multiprocess``) each node runs in
its own subprocess and connects to a shared :class:`ZMQBus`
endpoint.  The Node class is the same in both modes — the
distinction is which Bus the supervisor hands it.

The Track B audio_io / stt / tts nodes will all subclass this.
"""

from .base import Node, NodeState
from .stt import STTAdapter, STTNode
from .tts import Synthesizer, TTSNode
from .vision import CameraAdapter, TCPCameraAdapter, USBCameraAdapter, VisionNode

__all__ = [
    "Node", "NodeState",
    "TTSNode", "Synthesizer",
    "STTNode", "STTAdapter",
    "VisionNode", "CameraAdapter",
    "USBCameraAdapter", "TCPCameraAdapter",
]
