"""The voice — how JaegerAI uses the TTS module.

    slot: tts                jaeger-kokoro-tts fills it today
    consumes  /act/speech/say, /act/speech/stop, /act/speaker/state
    produces  /act/speech/spoken, /act/speech/chunk,
              /act/speaker/pcm, /act/speaker/stop

OPTIONAL. Nothing here raises when the module is absent; ``available()``
is what a surface asks before promising speech.

This integration deliberately carries Kokoro's real import name. A
different TTS module later gets its own named file — the point of the
directory is that an operator can see which provider is wired in.

The module does the heavy lifting (the neural synthesis, the voice
packs, PCM generation). This file only speaks its bus contract, which
is why it is short: the seam between an application and an engine
should be thin even when neither side is.
"""

from __future__ import annotations

from typing import Any

from jaeger_os import topics

from jaeger_ai.modules import installed

SLOT = "tts"

#: The exact import package integrated by this module file.
PACKAGE = "jaeger_kokoro_tts"

#: Topics a surface watches to follow the speech path.
WATCH = (
    topics.ACT_SPEECH_SAY,       # what was asked for
    topics.ACT_SPEECH_SPOKEN,    # the done-ack: ok, duration, reason
    topics.ACT_SPEECH_CHUNK,     # per-chunk AMPLITUDE — the lip-sync signal
    topics.ACT_SPEAKER_STATE,    # the device: playing or idle
)


def available() -> bool:
    return installed(PACKAGE)


def say(bus: Any, text: str) -> None:
    """Ask the configured TTS module to speak over its bus contract."""
    text = (text or "").strip()
    if text:
        bus.publish(topics.SpeechCommand(text=text))


def warm() -> dict[str, Any]:
    """Pre-load whatever fills ``tts`` so the first reply doesn't pay the
    weight-load tax. Idempotent.

    Prefer ``[config.tts] warm = true`` in the app manifest — a module
    that warms itself needs no app-side call at all, and that is the
    shape Mochi uses. This exists for the TUI boot path, which has no
    chassis Supervisor yet (see jaeger.toml's header) and so starts the
    node lazily instead of at boot.

    0.11.0: was ``jaeger_agent.tools.speak.warm_kokoro``. Warming an
    engine is the app's job — the mind should not know which module
    fills the slot, let alone hold its warm-up lifecycle. The body was
    always engine-neutral; only the name and its address were wrong.
    """
    from jaeger_os.nodes import runtime
    runtime.ensure_tts_node(warm=True)
    s = runtime.get_synth()
    if s is None:
        return {"warmed": False, "reason": "tts runtime not initialized"}
    return s.warm()


def synth() -> Any:
    """The live ``Synthesizer`` the tts node wraps, or ``None``.

    NON-EXECUTION configuration only — echo-cancellation reference
    buffer, audio backend selection, warm reporting. Speech itself goes
    over the bus through :func:`say`; a caller that reaches for this
    object to make sound is bypassing the contract this file exists to
    state.
    """
    from jaeger_os.nodes import runtime
    runtime.ensure_tts_node()
    return runtime.get_synth()


def stop(bus: Any) -> None:
    """Barge-in — TWO topics, deliberately.

    SpeechStop tells the engine to stop SYNTHESISING; SpeakerStop tells
    the driver to drop what is already queued at the device. Either
    alone leaves half a sentence playing, which is the half-second that
    makes an assistant feel deaf when you talk over it.
    """
    bus.publish(topics.SpeechStop())
    bus.publish(topics.SpeakerStop())


__all__ = ["SLOT", "PACKAGE", "WATCH", "available", "say", "stop"]
