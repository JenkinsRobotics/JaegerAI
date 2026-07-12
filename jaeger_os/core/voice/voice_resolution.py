"""Resolve which voice a TTS backend should speak with.

Moved out of ``agent/tools/speak.py`` in the 0.9 CI-dependency-rule pass
(dev/docs/vision/THREE_TIER_STRUCTURE.md, law 2): this is pure instance
config resolution (identity.yaml -> active character -> module default)
with no tool-calling concern at all. It was only living in ``agent/``
because that's where the ``speak`` tool happened to be defined, but
``jaeger_os.nodes.runtime.ensure_tts_node()`` — runtime tier — needs the
same resolution to build Kokoro with the right voice at node-boot time,
and runtime/hardware must never import ``agent/`` (the nervous-system
rule). Living in ``core.voice`` lets both ``agent/tools/speak.py`` and
``nodes/runtime.py`` import it without either one reaching into the
other's tier.
"""

from __future__ import annotations


def _module_default_voice() -> str:
    """The kokoro_tts module's OWN configured default voice — what
    :func:`resolve_voice` falls back to when neither the active
    character nor ``Identity.voice_id`` set one.

    Reads ``Config.kokoro_tts.voice`` (settings-catalog editable — see
    ``jaeger_os/nodes/kokoro_tts/config.py``) so changing it in
    config.yaml actually changes the spoken default; falls back to the
    module's own dataclass default when there's no instance to read
    yet (fresh boot, no layout bound)."""
    from jaeger_os.core.context import _require_layout
    from jaeger_os.nodes.kokoro_tts import KokoroTTSConfig
    try:
        layout = _require_layout()
        from jaeger_os.core.instance.schemas import Config, load_yaml
        return load_yaml(layout.config_path, Config).kokoro_tts.voice
    except Exception:
        return KokoroTTSConfig().voice


def resolve_voice() -> str:
    """Read the active instance's identity.yaml for a ``voice_id``
    override, falling back to the kokoro_tts module's configured
    default voice.

    Used by ``jaeger_os.nodes.runtime.ensure_tts_node()`` to build
    Kokoro with the right voice for the active instance (Jarvis vs.
    Lilith etc.) without each speak() call needing to know which
    instance is active."""
    from jaeger_os.core.context import _require_layout
    try:
        layout = _require_layout()
    except Exception:
        return _module_default_voice()
    try:
        from jaeger_os.personality.character import active_character
        ch = active_character(layout.root)
        if ch is not None and ch.voice_id:
            return ch.voice_id.strip()
    except Exception:
        pass
    from jaeger_os.core.instance.schemas import Identity, load_yaml
    try:
        identity = load_yaml(layout.identity_path, Identity)
    except Exception:
        return _module_default_voice()
    voice_id = (identity.voice_id or "").strip()
    return voice_id or _module_default_voice()


__all__ = ["resolve_voice"]
