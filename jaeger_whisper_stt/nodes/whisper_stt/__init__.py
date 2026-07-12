"""jaeger_whisper_stt.nodes.whisper_stt — the whisper_stt engine-module.

0.8 M2b: the second "engine-module" (kokoro_tts, M1, is the first) —
the module IS the engine. This package owns everything Whisper STT:
the bus-addressable ``AudioSessionNode`` (``node.py``), the real
pywhispercpp-backed engine — two algorithmic modes (``two_pass``,
``continuous``), a stubbed third (``local_agreement``), the shared
mic/VAD/wake-word helpers (``engine/_base.py``), and the method
registry that is the STT-mode swap point (``engine/registry.py``) —
plus its ``module.yaml`` manifest (module/slot/version/consumes/
produces/tools/factory/config/requires_libraries — the seam a future
module-loader/discovery layer reads; see
``dev/docs/history/JROS_0.8_M2b_WHISPER_STT_PLAN.md`` Task A).

Folded in from ``jaeger_os/nodes/audio_session/`` (the generic node),
``jaeger_os/nodes/stt/`` (a pre-1.0 back-compat import shim), and
``jaeger_os/plugins/whisper_stt/`` (the Whisper engine) — no back-compat
shims (pre-1.0 rule): those three paths are deleted, not aliased. Every
importer was rewired to this package.

The SLOT (``stt``) is the contract — topics, lifecycle, the ``listen``
tool. The manifest node id stays ``audio_session`` for continuity;
``core/audio/session.py``'s ``STTAdapter`` Protocol is what makes a
future sibling module (a different STT engine plugging into the same
slot) possible without touching ``core/audio/session.py`` or
``node.py``. ``core/audio/session.py`` itself STAYS in core — it's the
slot-generic mic/AEC/filter library any STT engine would use, not part
of this module.
"""

from __future__ import annotations

from typing import Any

from .config import WhisperSTTConfig
from .engine import WhisperSTT, WhisperSTTContinuous, WhisperSTTTwoPass
from .node import AudioSessionNode, STTAdapter, STTNode

__all__ = [
    "AudioSessionNode", "STTNode", "STTAdapter",
    "WhisperSTT", "WhisperSTTTwoPass", "WhisperSTTContinuous",
    "WhisperSTTConfig", "make_audio_session_node",
]


def make_audio_session_node(bus: Any, config: dict[str, Any]) -> AudioSessionNode:
    """Chassis-contract factory ``(bus, config) -> AudioSessionNode``.

    0.8 U3b: constructs the node DIRECTLY on the chassis-injected
    ``bus`` via ``runtime._build_audio_session_node`` rather than
    calling ``ensure_audio_session_node()`` — same recursion hazard as
    ``make_tts_node`` (the supervisor's ``ThreadHandle.start()`` calls
    this factory; ``ensure_audio_session_node()``'s supervisor branch
    would call right back into ``supervisor.start("audio_session")``).

    0.8 M2b Task B: the ``AudioSessionConfig`` this builds is now
    routed from real settings (``Config.whisper_stt`` + ``Config.voice``)
    instead of construction defaults — see
    ``runtime._load_audio_session_config``.
    """
    from jaeger_os.nodes.runtime import _build_audio_session_node
    return _build_audio_session_node(bus, config)
