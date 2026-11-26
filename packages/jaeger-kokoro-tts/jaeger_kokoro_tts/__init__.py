"""JaegerKokoroTTS — the ``kokoro_tts`` engine module.

The module IS the engine, and the PACKAGE is the module. This package
owns everything Kokoro: the bus-addressable ``TTSNode`` and the
``Synthesizer`` Protocol (``node.py``), the real Kokoro engine
(``engine.py``), both playback backends (``bus_player.py`` publishes to
the audio driver, ``persistent_player.py`` owns a device directly), the
settings-catalog slice (``config.py``), the standalone dev CLI
(``cli.py``), and the ``module.yaml`` manifest that declares
slot/topics/tools/factory to JaegerOS's discovery.

LAYOUT (0.12.0). Everything above sits at THIS package's root, the
canonical module-repo shape in Jaeger-Template's ``{{package_name}}/``,
matching the sibling ``jaeger_whisper_stt``. It used to live two levels
further down, under ``nodes/kokoro_tts/``, inherited from its old home
inside ``jaeger_os/nodes/`` where a ``nodes/`` package holding many
nodes made sense. In a repo shipping exactly one module it held one
entry, inside a package already called ``jaeger_kokoro_tts``, inside a
distribution already called ``jaeger-kokoro-tts`` — two directory levels
carrying no information. ``discover_modules()`` already supported a root
that IS a module (the singleton shape), so flattening cost one line in
``module_roots.py``.

This package directory sits inside the repo, NOT at the repo root, and
that level is not optional: ``import jaeger_kokoro_tts`` resolves to a
directory of exactly that name on ``sys.path``. Hoisting the code to the
repo root would make the import name the clone's folder name and drag
``pyproject.toml`` and ``.git`` inside the importable package.

Pins ``jaeger-os`` only — never ``jaeger-ai`` — so a robot body (JP01
and friends) can speak without the AI product installed at all.

The SLOT (``tts``) is the contract — topics, lifecycle, the
``text_to_speech`` tool. Swapping engines means installing a sibling
module that claims the same slot; ``node.py``'s ``Synthesizer`` Protocol
is what makes that swap possible without touching the node.
"""

from __future__ import annotations

from typing import Any

from .config import KokoroTTSConfig
from .engine import (
    KOKORO_LANG,
    KOKORO_SAMPLE_RATE,
    KOKORO_VOICE,
    KokoroTTS,
)
try:
    from .node import Synthesizer, TTSNode
except ImportError:
    Synthesizer = Any  # type: ignore[assignment,misc]
    TTSNode = Any  # type: ignore[assignment,misc]

__version__ = "0.13.0"

__all__ = [
    "TTSNode", "Synthesizer", "KokoroTTS",
    "KOKORO_VOICE", "KOKORO_LANG", "KOKORO_SAMPLE_RATE",
    "KokoroTTSConfig", "make_tts_node", "open_voice", "__version__",
]


def open_voice(*, voice: str = KOKORO_VOICE, language: str = KOKORO_LANG) -> KokoroTTS:
    """A loaded, primed voice for a caller that plays the audio itself.

    The ``tts`` slot's direct call, next to ``make_tts_node`` (the bus
    node). Whatever module fills the slot exports this name and returns
    an object with ``synth(text)`` (float32 mono chunks, as rendered),
    ``sample_rate`` and ``compute``. No bus, no audio device.
    """
    tts = KokoroTTS(voice=voice, lang=language)
    for _ in tts.synth("ready"):    # first render pays the warm-up, not the first line
        pass
    return tts


def make_tts_node(bus: Any, config: dict[str, Any]) -> TTSNode:
    """Build a self-contained JaegerOS TTS node on the injected bus.

    The module owns its engine construction and warm-up lifecycle; it does
    not reach into JaegerOS runtime globals or private factory functions.
    This is the same entry point used by an in-process app and a supervised
    robot deployment.
    """
    cfg = dict(config or {})
    settings = KokoroTTSConfig(**{
        key: value for key, value in cfg.items()
        if key in KokoroTTSConfig.model_fields
    })
    synth = KokoroTTS(
        voice=settings.voice,
        lang=settings.lang,
        bus=bus,
    )
    return TTSNode(
        bus=bus,
        synthesizer=synth,
        name=str(cfg.get("name") or "tts"),
        queue_maxsize=settings.queue_maxsize,
        max_text_chars=settings.max_text_chars,
        warm_on_start=settings.warm,
        install_signal_handlers=False,
    )


make_tts_node.__node_class__ = TTSNode
