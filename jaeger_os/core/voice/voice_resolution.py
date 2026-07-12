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

0.9 step 4 split: every cross-tier lookup below (instance context,
Config schema, active character, kokoro's own config) now resolves
through ``core.modules``'s discovery helpers instead of a hardcoded
dotted import — the owning packages (the Mind, the tts engine) are
separate installed packages post-split, so their dotted paths aren't
knowable at write-time. Absent-Mind / absent-engine both degrade to
the empty-string default, same fail-soft shape as before.
"""

from __future__ import annotations

from jaeger_os.core.modules import resolve_mind_module, resolve_slot_symbols


def _module_default_voice() -> str:
    """The kokoro_tts module's OWN configured default voice — what
    :func:`resolve_voice` falls back to when neither the active
    character nor ``Identity.voice_id`` set one.

    Reads ``Config.kokoro_tts.voice`` (settings-catalog editable — see
    ``jaeger_os/nodes/kokoro_tts/config.py``) so changing it in
    config.yaml actually changes the spoken default; falls back to the
    module's own dataclass default when there's no instance to read
    yet (fresh boot, no layout bound)."""
    context_mod = resolve_mind_module("core.context")
    KokoroTTSConfig = resolve_slot_symbols("tts", ("KokoroTTSConfig",)).get(
        "KokoroTTSConfig")
    try:
        layout = context_mod._require_layout()
        schemas_mod = resolve_mind_module("core.instance.schemas")
        return schemas_mod.load_yaml(layout.config_path,
                                      schemas_mod.Config).kokoro_tts.voice
    except Exception:
        return KokoroTTSConfig().voice if KokoroTTSConfig is not None else ""


def resolve_voice() -> str:
    """Read the active instance's identity.yaml for a ``voice_id``
    override, falling back to the kokoro_tts module's configured
    default voice.

    Used by ``jaeger_os.nodes.runtime.ensure_tts_node()`` to build
    Kokoro with the right voice for the active instance (Jarvis vs.
    Lilith etc.) without each speak() call needing to know which
    instance is active."""
    context_mod = resolve_mind_module("core.context")
    try:
        layout = context_mod._require_layout()
    except Exception:
        return _module_default_voice()
    try:
        personality_mod = resolve_mind_module("personality.character")
        ch = personality_mod.active_character(layout.root)
        if ch is not None and ch.voice_id:
            return ch.voice_id.strip()
    except Exception:
        pass
    try:
        schemas_mod = resolve_mind_module("core.instance.schemas")
        identity = schemas_mod.load_yaml(layout.identity_path, schemas_mod.Identity)
    except Exception:
        return _module_default_voice()
    voice_id = (identity.voice_id or "").strip()
    return voice_id or _module_default_voice()


__all__ = ["resolve_voice"]
