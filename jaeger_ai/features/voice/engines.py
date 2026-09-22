"""How the voice client builds its engines.

Engines come from the application's module slots: ``stt`` (filled by
jaeger-whisper-stt) and ``tts`` (filled by jaeger-kokoro-tts). What they can
do on this machine is measured in :mod:`jaeger_ai.core.voice.status`. This
file never picks a model for the *mind*; cognition belongs to the Entity.
"""
from __future__ import annotations

from typing import Any


def make_microphone_listener(model_name: str = "base.en", **kwargs: Any) -> Any:
    """The stt slot's continuous Whisper engine on the default microphone."""
    from jaeger_whisper_stt.nodes.whisper_stt.engine import WhisperSTTContinuous

    return WhisperSTTContinuous(model_name=model_name, **kwargs)


def make_kokoro_speaker(**kwargs: Any) -> Any:
    """The tts slot's Kokoro engine on the default output device."""
    from jaeger_kokoro_tts.nodes.kokoro_tts.engine import KokoroTTS

    return KokoroTTS(**kwargs)
