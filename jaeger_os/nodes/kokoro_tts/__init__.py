"""jaeger_os.nodes.kokoro_tts — the kokoro_tts engine-module.

0.8 M1: the first "engine-module" — the module IS the engine. This
package owns everything Kokoro: the generic ``TTSNode`` + ``Synthesizer``
Protocol (``node.py``), the real ``KokoroTTS`` engine + persistent audio
player (``engine.py`` / ``persistent_player.py``), its own settings-
catalog config slice (``config.py``, nested at ``Config.kokoro_tts``),
and its ``module.yaml`` manifest (module/slot/version/consumes/produces/
tools/factory/config — the seam a future module-loader/discovery layer
reads; see ``dev/docs/JROS_0.8_M1_KOKORO_TTS_PLAN.md`` Task 2).

Folded in from ``jaeger_os/nodes/tts/`` (the generic node) and
``jaeger_os/plugins/kokoro_tts/`` (the Kokoro engine) — no back-compat
shims (pre-1.0 rule): those two paths are deleted, not aliased. Every
importer was rewired to this package.

The SLOT (``tts``) is the contract — topics, lifecycle, the ``speak``
tool. Swapping engines later means adding a sibling module (e.g. a future
``nodes/apple_tts/``) that plugs into the same slot; ``node.py``'s
``Synthesizer`` Protocol is what makes that swap possible without
touching the node.
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
from .node import Synthesizer, TTSNode

__all__ = [
    "TTSNode", "Synthesizer", "KokoroTTS",
    "KOKORO_VOICE", "KOKORO_LANG", "KOKORO_SAMPLE_RATE",
    "KokoroTTSConfig", "make_tts_node",
]


def make_tts_node(bus: Any, config: dict[str, Any]) -> TTSNode:
    """Chassis-contract factory ``(bus, config) -> TTSNode``.

    0.8 U3b: constructs the node DIRECTLY on the chassis-injected
    ``bus`` via ``runtime._build_tts_node`` rather than calling
    ``ensure_tts_node()`` — the supervisor's ``ThreadHandle`` invokes
    this factory from inside ``ThreadHandle.start()``, and
    ``ensure_tts_node()``'s supervisor-delegation branch would call
    right back into ``supervisor.start("tts")``, recursing into the
    very ``start()`` call this factory is running inside of. See
    ``jaeger_os/nodes/runtime.py``'s ``_build_tts_node`` docstring.
    """
    from jaeger_os.nodes.runtime import _build_tts_node
    return _build_tts_node(bus, config)
