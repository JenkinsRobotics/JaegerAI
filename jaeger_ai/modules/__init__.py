"""The imported Jaeger modules JaegerAI integrates, one file each.

Same convention as Mochi's ``modules/``: a file per imported module,
named for the REAL import package, so an operator reading the directory
sees which provider is wired in without tracing discovery. A generic
``tts.py`` would hide that; ``jaeger_kokoro_tts.py`` cannot.

    modules/
      jaeger_agent.py         slot: mind — the brain
      jaeger_kokoro_tts.py    slot: tts  — the voice
      jaeger_whisper_stt.py   slot: stt  — the ears

Each file carries JaegerAI's commands and observations for that module:
``SLOT``, ``PACKAGE``, the ``WATCH`` topics a surface follows, an
``available()`` gate, and thin verbs that publish the module's bus
contract. Engine logic lives in the module's own package — nothing here
imports one. That is the whole point: these files talk to a contract, so
swapping Kokoro for Piper means writing a sibling file, not editing
JaegerAI.

Only IMPORTED modules belong here. JaegerAI's own in-tree nodes
(``jaeger_ai/nodes/`` — animation, media) and plugins (messaging, MCP)
are not imported modules and keep their existing homes; see
``jaeger_ai/module_roots.py`` for what this package registers with
JaegerAI discovery.
"""

from __future__ import annotations

import importlib.util


def installed(package: str) -> bool:
    """Is the module's package importable?

    Integrations use this to degrade rather than crash. "No voice
    installed" is a usable state — JaegerAI ran for years without one —
    but an ImportError at boot is not.

    Probes with ``find_spec`` rather than importing: cheap, and it does
    not drag a model-loading module into memory just to answer whether
    it exists.
    """
    try:
        return importlib.util.find_spec(package) is not None
    except (ImportError, ValueError):
        return False


def summary() -> list[dict[str, object]]:
    """One row per integrated module: slot, package, installed.

    What a ``/modules`` panel or ``jaeger doctor`` prints to answer
    "which provider is actually filling each slot?".
    """
    from . import jaeger_agent, jaeger_kokoro_tts, jaeger_whisper_stt

    return [
        {"slot": m.SLOT, "package": m.PACKAGE, "installed": m.available()}
        for m in (jaeger_agent, jaeger_kokoro_tts, jaeger_whisper_stt)
    ]


__all__ = ["installed", "summary"]
