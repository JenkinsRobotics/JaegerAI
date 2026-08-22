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
from .light import LightAdapter, LightNode, SerialLightAdapter
from .motor import MotorAdapter, MotorNode, SerialMotorAdapter
from .vision import CameraAdapter, TCPCameraAdapter, USBCameraAdapter, VisionNode

# 0.9 step 4 split: kokoro_tts/whisper_stt stopped being nested
# submodules of jaeger_os.nodes (``.kokoro_tts`` / ``.whisper_stt``) and
# became wholly separate installed packages (jaeger_kokoro_tts,
# jaeger_whisper_stt) — a hardcoded ``from .kokoro_tts import ...``
# relative import can no longer even ATTEMPT to resolve them. Resolved
# via ``core.modules.resolve_slot_symbols`` (discover_modules() + the
# winning module's factory-string module) instead — the same discovery
# path app/app.py's slot-binding already uses (M2a pattern), so
# whichever package actually ships the tts/stt module (in this tree or
# any other installed one) is found the same way.
#
# LAZY via module ``__getattr__`` (PEP 562), NOT resolved eagerly at
# import time — found the hard way (0.9 step 4 gate 1): the engine
# packages' own node.py does ``from jaeger_os.nodes.base import Node``,
# so whichever import chain reaches the engine package FIRST can
# re-enter THIS package mid-initialization. If jaeger_os.nodes'
# discovery eagerly imports the engine module at that exact moment, it
# gets the engine's PARTIALLY-initialized module object back from
# sys.modules (Python's own reentrant-import guard) — TTSNode/
# Synthesizer aren't SET on it yet, so eager resolution permanently
# caches None even though the engine is genuinely installed and works
# fine a moment later. Resolving on first ACCESS instead (long after
# all modules have finished importing) sidesteps the race entirely.
# Absent (no module installed for the slot) resolves every name to
# None, same fail-soft shape as the old ImportError guard — the
# availability gate (agent/availability.py's ``_module_ready``) is what
# fails the actual tool closed, this is just import-time tolerance.
from jaeger_os.core.modules import resolve_slot_symbols as _resolve_slot_symbols

_TTS_NAMES = ("Synthesizer", "TTSNode")
_STT_NAMES = ("AudioSessionNode", "STTAdapter", "STTNode")


def __getattr__(name: str):
    if name in _TTS_NAMES:
        return _resolve_slot_symbols("tts", _TTS_NAMES).get(name)
    if name in _STT_NAMES:
        return _resolve_slot_symbols("stt", _STT_NAMES).get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Node", "NodeState",
    "TTSNode", "Synthesizer",
    "AudioSessionNode", "STTNode", "STTAdapter",
    "VisionNode", "CameraAdapter",
    "USBCameraAdapter", "TCPCameraAdapter",
    "MotorNode", "MotorAdapter", "SerialMotorAdapter",
    "LightNode", "LightAdapter", "SerialLightAdapter",
]
