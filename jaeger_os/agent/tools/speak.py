"""Text-to-speech tool shims — route through the 0.4 TTS node.

  • speak(text=, path=) — publish /act/speech, wait for /sense/spoken
  • warm_kokoro()       — pre-load the Kokoro pipeline at startup

0.4 rewire (Track B.2): the tool used to call ``KokoroTTS.speak()``
directly in-process.  It now publishes a :class:`SpeechCommand` on
the brain's bus and blocks until the TTS node returns a
:class:`SpokenAck` with the matching ``correlation_id``.

The agent's tool surface is unchanged — same function name, same
arguments, same return-dict shape.  What changed is who actually
runs the synthesis: the TTS node owns Kokoro now, not this module.
That preserves the operator's lock-in: "**a tool does the
networking, the node does the execution**."

Sandbox check for ``path=`` stays here in core, BEFORE the bus
publish — file-resolution boundaries must hold regardless of which
TTS backend the node wraps.
"""

from __future__ import annotations

import uuid
from typing import Any

from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
from jaeger_os.core.context import SandboxError, _require_layout, _resolve_under

# Re-export the module's constants so existing imports keep working.
try:
    from ...nodes.kokoro_tts import (
        KOKORO_LANG,
        KOKORO_SAMPLE_RATE as KOKORO_SAMPLE_RATE,
        KOKORO_VOICE as KOKORO_VOICE,
        KokoroTTS,
    )
except ImportError:
    # 0.8 M2a: kokoro_tts module removed from this deployment. These
    # constants are only ever read while actually synthesizing speech
    # (``_get_tts``'s fallback branch, ``_module_default_voice``'s
    # except branch) — paths the ``_speak_via_bus`` early-return below
    # keeps the agent from ever reaching when the module's gone.
    # Fallbacks mirror kokoro_tts/engine.py's own defaults so nothing
    # downstream sees a surprising type.
    KOKORO_LANG = "a"
    KOKORO_SAMPLE_RATE = 24000
    KOKORO_VOICE = "af_heart"
    KokoroTTS = None  # type: ignore[assignment,misc]


# How long the brain's tool waits for the TTS node to publish
# /sense/spoken.  Long enough for a multi-minute narration; short
# enough that a genuinely wedged node surfaces as a timeout instead
# of a permanent hang.
_SPEAK_TIMEOUT_S = 180.0


def _module_default_voice() -> str:
    """The kokoro_tts module's OWN configured default voice — what
    :func:`_resolve_voice` falls back to when neither the active
    character nor ``Identity.voice_id`` set one.

    Reads ``Config.kokoro_tts.voice`` (settings-catalog editable — see
    ``jaeger_os/nodes/kokoro_tts/config.py``) so changing it in
    config.yaml actually changes the spoken default; falls back to the
    module's own dataclass default when there's no instance to read
    yet (fresh boot, no layout bound)."""
    from jaeger_os.nodes.kokoro_tts import KokoroTTSConfig
    try:
        layout = _require_layout()
        from jaeger_os.core.instance.schemas import Config, load_yaml
        return load_yaml(layout.config_path, Config).kokoro_tts.voice
    except Exception:
        return KokoroTTSConfig().voice


def _resolve_voice() -> str:
    """Read the active instance's identity.yaml for a ``voice_id``
    override, falling back to the kokoro_tts module's configured
    default voice.

    Used by ``jaeger_os.nodes.runtime.ensure_tts_node()`` to build
    Kokoro with the right voice for the active instance (Jarvis vs.
    Lilith etc.) without each speak() call needing to know which
    instance is active."""
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


def warm_kokoro() -> dict[str, Any]:
    """Pre-load Kokoro so the first ``speak()`` doesn't pay the
    ~5-7 s weight-load tax.  Idempotent.

    0.4 (Track B.2): also boots the TTS node + bus runtime so the
    first ``speak()`` call doesn't pay the node-spinup tax either."""
    from jaeger_os.nodes import runtime
    runtime.ensure_tts_node(warm=True)
    synth = runtime.get_synth()
    if synth is None:
        return {"warmed": False, "reason": "tts runtime not initialized"}
    # Return Kokoro's own warm report (the dict the pre-0.4 caller
    # got back).  warm() is idempotent — second call returns the
    # cached state.
    return synth.warm()


def _get_tts() -> KokoroTTS:
    """Back-compat accessor for backend setup around the TTS node.

    The speech execution path is bus-routed now.  A few voice
    coordinators still need the wrapped KokoroTTS instance for
    non-execution configuration such as AEC reference-buffer wiring,
    audio backend selection, and warm status reporting.
    """
    from jaeger_os.nodes import runtime
    runtime.ensure_tts_node()
    synth = runtime.get_synth()
    if synth is None:
        # Fallback path: construct directly.  Shouldn't happen since
        # ensure_tts_node() above always materialises a synth, but
        # if some startup ordering surprise leaves runtime empty we
        # still want a working KokoroTTS instead of crashing.
        return KokoroTTS(voice=_resolve_voice(), lang=KOKORO_LANG)
    return synth


def speak(text: str = "", path: str = "") -> dict[str, Any]:
    """Speak aloud through the default audio output via the TTS node.

    Pass ``text`` to speak literal text, or ``path`` to narrate a
    file from ``<instance>/skills/`` ("read X out loud", "narrate X").
    When ``path`` is given it wins.  Supports minimal SSML:
    ``<speak>``, ``<break time="Xms"/>``, ``<breath/>``.

    The ``path`` branch is sandbox-resolved through the same logic
    as ``file_read`` — it must stay inside the instance's ``skills/``
    zone.  Sandbox check lives here in core (not in the node) so
    swapping out the TTS backend can't relax file-access boundaries.

    0.4 routing
    -----------
    Publishes :class:`SpeechCommand` on the brain bus, waits up to
    ``_SPEAK_TIMEOUT_S`` seconds for the TTS node to publish a
    matching :class:`SpokenAck`.  Returns a dict matching the
    pre-0.4 shape (``spoken``, ``elapsed_s``, ``reason``,
    ``from_file``) so callers don't see the rewire.
    """
    file_path = (path or "").strip()
    if file_path:
        layout = _require_layout()
        try:
            target = _resolve_under(layout.skills_dir, file_path)
        except SandboxError as exc:
            return {"spoken": False, "reason": str(exc), "path": file_path}
        if not target.exists() or not target.is_file():
            return {"spoken": False, "reason": "file not found",
                    "path": file_path}
        body = target.read_text(encoding="utf-8")
        result = _speak_via_bus(body)
        result["from_file"] = str(target.relative_to(layout.root))
        return result

    if not (text or "").strip():
        return {"spoken": False,
                "reason": "nothing to speak — pass text or path"}
    return _speak_via_bus(text)


def _tts_module_present() -> bool:
    """True iff the ``tts`` slot has a discovered, ready module.

    0.8 M2a: lets :func:`_speak_via_bus` return immediately instead of
    spinning up the runtime and blocking on ``bus.request`` for
    ``_SPEAK_TIMEOUT_S`` (180 s) when kokoro_tts has been removed from
    the deployment. Prefers the availability gate's own module-
    readiness check (the same one that hides ``text_to_speech`` from
    the agent) since it's already authoritative for this tool; falls
    back to a raw slot-discovery check if that import ever fails for
    an unrelated reason, so a broken availability module doesn't turn
    into a false "module missing"."""
    try:
        from jaeger_os.agent.availability import _module_ready
        ready = _module_ready("text_to_speech")
        if ready is not None:
            return ready
    except Exception:  # noqa: BLE001 — gate import must never block speak
        pass
    try:
        from jaeger_os.core.modules import discover_modules
        return bool(discover_modules().get("tts"))
    except Exception:  # noqa: BLE001
        return True  # fail-open: don't block speak because discovery broke


def _speak_via_bus(text: str) -> dict[str, Any]:
    """Publish a :class:`SpeechCommand` and block on the matching
    :class:`SpokenAck`.  Returns a dict shaped like the pre-0.4
    in-process result for backward-compatible callers."""
    if not _tts_module_present():
        return {"spoken": False, "reason": "no tts module installed"}

    from jaeger_os.transport import topics
    from jaeger_os.nodes import runtime

    # Ensure the node + bus are up.  Idempotent — pays the spinup
    # cost only on the very first call (which warm_kokoro should
    # have already covered at boot).
    runtime.ensure_tts_node()
    bus = runtime.get_bus()

    cid = uuid.uuid4().hex
    request = topics.SpeechCommand(
        text=text,
        voice=_resolve_voice(),
        node_id="brain",
        correlation_id=cid,
    )
    ack = bus.request(
        request,
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=_SPEAK_TIMEOUT_S,
    )
    if ack is None:
        return {
            "spoken": False,
            "reason": f"TTS node timeout after {_SPEAK_TIMEOUT_S}s",
            "elapsed_s": _SPEAK_TIMEOUT_S,
        }
    return {
        "spoken": ack.ok,
        "elapsed_s": ack.duration_s,
        "reason": ack.reason,
    }


# ── Agent-tool wrapper (migrated from main.py::_register_builtins) ──


@register_tool_from_function(name="text_to_speech")
def _t_text_to_speech(text: str = "", path: str = "") -> dict:
    """Speak text aloud through the default audio output via Kokoro
    TTS. Use ONLY when the user explicitly asks to HEAR something
    ("say…", "out loud", "narrate/read X aloud", "speak"). This is
    NOT your reply channel — ordinary questions ("tell me a joke",
    "what's the weather") are answered in text, not spoken.
    Pass `text` for literal text, or `path` to narrate a file from
    <instance>/skills/ ("read X out loud", "narrate X" with a named
    file). `path` is sandbox-resolved and wins over `text` when both
    are given. Supports minimal SSML: <break time="200ms"/>, <breath/>."""
    return speak(text=text, path=path)
