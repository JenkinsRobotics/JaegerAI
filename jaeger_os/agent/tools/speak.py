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

from jaeger_os.core.context import SandboxError, _require_layout, _resolve_under

# Re-export plugin constants so existing imports keep working.
from ...plugins.kokoro_tts import (
    KOKORO_LANG,
    KOKORO_SAMPLE_RATE as KOKORO_SAMPLE_RATE,
    KOKORO_VOICE,
    KokoroTTS,
)


# How long the brain's tool waits for the TTS node to publish
# /sense/spoken.  Long enough for a multi-minute narration; short
# enough that a genuinely wedged node surfaces as a timeout instead
# of a permanent hang.
_SPEAK_TIMEOUT_S = 180.0


def _resolve_voice() -> str:
    """Read the active instance's identity.yaml for a ``voice_id``
    override, falling back to the plugin's KOKORO_VOICE default.

    Used by ``jaeger_os.nodes.runtime.ensure_tts_node()`` to build
    Kokoro with the right voice for the active instance (Jarvis vs.
    Lilith etc.) without each speak() call needing to know which
    instance is active."""
    try:
        layout = _require_layout()
    except Exception:
        return KOKORO_VOICE
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
        return KOKORO_VOICE
    voice_id = (identity.voice_id or "").strip()
    return voice_id or KOKORO_VOICE


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


def _speak_via_bus(text: str) -> dict[str, Any]:
    """Publish a :class:`SpeechCommand` and block on the matching
    :class:`SpokenAck`.  Returns a dict shaped like the pre-0.4
    in-process result for backward-compatible callers."""
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
