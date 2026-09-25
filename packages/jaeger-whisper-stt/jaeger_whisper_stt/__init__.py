"""JaegerWhisperSTT — the ``whisper_stt`` engine module.

The module IS the engine, and the PACKAGE is the module. This package
owns everything Whisper STT: the bus-addressable ``AudioSessionNode``
(``node.py``), the settings-catalog slice (``config.py``), the
pywhispercpp-backed engine with its six methods and the registry that
swaps between them (``engine/``), the standalone dev CLI (``cli.py``),
and the ``module.yaml`` manifest that declares slot/topics/tools/factory
to JaegerOS's discovery.

LAYOUT (0.12.0). Everything above sits at THIS package's root, which is
the canonical module-repo shape in Jaeger-Template's
``{{package_name}}/``. It used to live two levels further down, under
``nodes/whisper_stt/``, because it was folded in from
``jaeger_os/nodes/audio_session/`` + ``jaeger_os/plugins/whisper_stt/``
during the 0.9 split and kept the path it had INSIDE the framework.
That path made sense there — ``jaeger_os.nodes`` holds many nodes — and
makes none here: a ``nodes/`` package containing exactly one entry, and
a ``whisper_stt/`` package inside a distribution already called
``jaeger-whisper-stt``, were two directory levels carrying no
information. ``discover_modules()`` already supported a root that IS a
module (the singleton shape ``AGENT_DIR`` uses), so flattening cost one
line in ``module_roots.py``.

This package directory sits inside the repo, NOT at the repo root, and
that one level is not optional: ``import jaeger_whisper_stt`` resolves
to a directory of exactly that name on ``sys.path``. Hoisting the code
to the repo root would make the import name the repo folder's name
(``JaegerWhisperSTT`` — wrong case, and it changes if anyone renames
their clone) and would drag ``pyproject.toml``, ``README.md`` and
``.git`` inside the importable package. Jaeger-Template has the same
split: ``{{package_name}}/`` is a directory beside ``pyproject.toml``,
never instead of it.

Pins ``jaeger-os`` only — never ``jaeger-ai`` — so a robot body (JP01
and friends) can listen without the AI product installed at all.

The SLOT (``stt``) is the contract: topics, lifecycle, the ``listen``
tool. ``jaeger_os.core.audio.session``'s ``STTAdapter`` Protocol is what
lets a different STT engine fill the same slot without anyone touching
``session.py`` or ``node.py``. That session module STAYS in JaegerOS —
it is the slot-generic mic/filter library any STT engine would use, not
part of this one.
"""

from __future__ import annotations

import importlib
from typing import Any

from .config import WhisperSTTConfig
from .node import AudioSessionNode, STTAdapter, STTNode
from .offline import (
    OfflineTranscriber, TranscriptSegment, TranscriptionResult,
    write_transcripts,
)
from .models import ModelStatus, cached_model_path, model_status, prepare_model

__version__ = "0.13.0"

_ENGINE_EXPORTS = {
    "WhisperSTT": (".engine.two_pass", "WhisperSTTTwoPass"),
    "WhisperSTTTwoPass": (".engine.two_pass", "WhisperSTTTwoPass"),
    "WhisperSTTContinuous": (".engine.continuous", "WhisperSTTContinuous"),
    "WhisperSTTPhraseWord": (".engine.phrase_word", "WhisperSTTPhraseWord"),
    "WhisperSTTWindow": (".engine.window", "WhisperSTTWindow"),
    "WhisperSTTLocalAgreement": (
        ".engine.local_agreement", "WhisperSTTLocalAgreement"),
}


def __getattr__(name: str):
    """Load convenience engine exports only when a caller requests one.

    The Jaeger module factory needs only the config and node above.
    Eagerly importing every algorithm made one broken optional method
    capable of taking down otherwise-working STT during app discovery.
    """
    target = _ENGINE_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(importlib.import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = [
    "AudioSessionNode", "STTNode", "STTAdapter",
    "WhisperSTTConfig", "make_audio_session_node", "__version__",
    "OfflineTranscriber", "TranscriptSegment", "TranscriptionResult",
    "write_transcripts",
    "ModelStatus", "cached_model_path", "model_status", "prepare_model",
    *_ENGINE_EXPORTS,
]


def make_audio_session_node(bus: Any, config: dict[str, Any]) -> AudioSessionNode:
    """Chassis-contract factory ``(bus, config) -> AudioSessionNode``.

    Constructs the node DIRECTLY on the chassis-injected ``bus`` via
    ``runtime._build_audio_session_node`` rather than calling
    ``ensure_audio_session_node()`` — same recursion hazard as
    ``make_tts_node`` (the supervisor's ``ThreadHandle.start()`` calls
    this factory; ``ensure_audio_session_node()``'s supervisor branch
    would call right back into ``supervisor.start("audio_session")``).

    ``config`` is this node's manifest ``[config.<key>]`` table and IS
    read — it overlays the instance settings, so an app can pick an STT
    method in its jaeger.toml without a Mind installed.
    """
    from jaeger_os.nodes.runtime import _build_audio_session_node
    return _build_audio_session_node(bus, config)
