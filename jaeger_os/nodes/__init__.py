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

The Track B audio_session / tts nodes will all subclass this.
"""

from .base import Node, NodeState
from .audio_session import AudioSessionNode, STTAdapter, STTNode
from .light import LightAdapter, LightNode, SerialLightAdapter
from .motor import MotorAdapter, MotorNode, SerialMotorAdapter
try:
    from .kokoro_tts import Synthesizer, TTSNode
except ImportError:
    # 0.8 M2a: kokoro_tts is an engine-module (jaeger_os/nodes/kokoro_tts/)
    # that can be removed from a deployment entirely. The names stay
    # importable (``from jaeger_os.nodes import TTSNode`` still resolves)
    # so nothing crashes at import time; the availability gate
    # (agent/availability.py's ``_module_ready``) already fails closed on
    # ``text_to_speech`` when discovery finds no kokoro_tts module.
    Synthesizer = None  # type: ignore[assignment,misc]
    TTSNode = None  # type: ignore[assignment,misc]
from .vision import CameraAdapter, TCPCameraAdapter, USBCameraAdapter, VisionNode

__all__ = [
    "Node", "NodeState",
    "TTSNode", "Synthesizer",
    "AudioSessionNode", "STTNode", "STTAdapter",
    "VisionNode", "CameraAdapter",
    "USBCameraAdapter", "TCPCameraAdapter",
    "MotorNode", "MotorAdapter", "SerialMotorAdapter",
    "LightNode", "LightAdapter", "SerialLightAdapter",
]
