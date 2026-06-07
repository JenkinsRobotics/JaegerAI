"""Shared realtime voice audio session.

``AudioSession`` is the library-layer owner for mic/STT coordination:
AEC setup, Whisper adapter construction, pause/follow-up/drain control,
non-speech filtering, and optional self-speech rejection.  It is not a
node by itself; ``AudioSessionNode`` wraps it for bus publication.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from jaeger_os.core.voice import is_non_speech_marker


class STTAdapter(Protocol):
    """The STT-shaped surface used by the audio session."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def next_phrase(self, timeout: float | None = 1.0) -> str | None: ...
    def set_paused(self, paused: bool) -> None: ...
    def set_on_speech_detected(self, callback: Callable[[], None] | None) -> None: ...
    def open_followup(self) -> None: ...
    def drain_pending(self) -> None: ...


@dataclass(frozen=True)
class AudioSessionConfig:
    """Construction settings for a realtime voice session."""

    stt_mode: str = "two_pass"
    fast_model_name: str = "base.en"
    accurate_model_name: str = "medium.en"
    require_wake_word: bool = False
    wake_phrases: tuple[str, ...] = ()
    followup_window_s: float = 10.0
    barge_in: bool = False
    audio_backend: str = "sounddevice"
    self_speech_filter: bool = False
    self_speech_threshold: float = 0.85


class AudioSession:
    """Own mic/AEC/STT state for one realtime voice session.

    In monolithic mode this session deliberately shares the TTS
    synthesizer's ``reference_buffer`` object in-process so AEC can stay
    aligned without streaming raw speaker audio through the bus.  That is
    a known monolithic-only coupling; the multiprocess path should replace
    it with a dedicated TTS reference topic when raw audio needs to cross
    a process boundary.
    """

    def __init__(
        self,
        *,
        adapter: STTAdapter,
        aec: Any = None,
        reference_buffer: Any = None,
        barge_in_live: bool = False,
        self_speech_filter: bool = False,
        self_speech_threshold: float = 0.85,
    ) -> None:
        self.adapter = adapter
        self.aec = aec
        self.reference_buffer = reference_buffer
        self.barge_in_live = barge_in_live
        self.self_speech_filter = self_speech_filter
        self.self_speech_threshold = self_speech_threshold
        self.last_reply_text = ""

    @classmethod
    def build(
        cls,
        config: AudioSessionConfig,
        *,
        tts_synth: Any = None,
    ) -> "AudioSession":
        """Build the production Whisper-backed audio session."""
        aec = None
        reference_buffer = None
        barge_in_live = False
        if config.barge_in:
            try:
                from jaeger_os.core.audio import (
                    AECWrapper,
                    ReferenceBuffer,
                    aec_available,
                )

                if aec_available():
                    aec = AECWrapper(sample_rate=16000, frame_ms=10, enabled=True)
                    reference_buffer = getattr(tts_synth, "reference_buffer", None)
                    if reference_buffer is None:
                        reference_buffer = ReferenceBuffer(
                            sample_rate=16000,
                            capacity_seconds=2.0,
                        )
                        if tts_synth is not None:
                            tts_synth.reference_buffer = reference_buffer
                    barge_in_live = True
            except Exception:  # noqa: BLE001
                aec = None
                reference_buffer = None
                barge_in_live = False

        adapter = cls._build_adapter(config, aec=aec, reference_buffer=reference_buffer)
        return cls(
            adapter=adapter,
            aec=aec,
            reference_buffer=reference_buffer,
            barge_in_live=barge_in_live,
            self_speech_filter=config.self_speech_filter,
            self_speech_threshold=config.self_speech_threshold,
        )

    @staticmethod
    def _build_adapter(
        config: AudioSessionConfig,
        *,
        aec: Any,
        reference_buffer: Any,
    ) -> STTAdapter:
        wake_phrases = config.wake_phrases or _default_wake_phrases()
        if config.stt_mode == "continuous":
            from jaeger_os.plugins.whisper_stt import WhisperSTTContinuous

            return WhisperSTTContinuous(
                model_name=config.fast_model_name,
                require_wake_word=config.require_wake_word,
                wake_phrases=wake_phrases,
                followup_window_s=config.followup_window_s,
                aec=aec,
                far_end_buffer=reference_buffer,
                audio_backend=config.audio_backend,
            )
        from jaeger_os.plugins.whisper_stt import WhisperSTTTwoPass

        return WhisperSTTTwoPass(
            fast_model_name=config.fast_model_name,
            accurate_model_name=config.accurate_model_name,
            require_wake_word=config.require_wake_word,
            wake_phrases=wake_phrases,
            followup_window_s=config.followup_window_s,
            aec=aec,
            far_end_buffer=reference_buffer,
            audio_backend=config.audio_backend,
        )

    def start(self) -> None:
        self.adapter.start()

    def stop(self) -> None:
        self.adapter.stop()

    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Return the next cleaned phrase, or ``None`` if nothing useful
        is ready within ``timeout``."""
        phrase = self.adapter.next_phrase(timeout=timeout)
        text = (phrase or "").strip()
        if not text or is_non_speech_marker(text):
            return None
        if self._is_self_speech(text):
            return None
        return text

    def set_paused(self, paused: bool) -> None:
        self.adapter.set_paused(paused)

    def set_on_speech_detected(
        self,
        callback: Callable[[], None] | None,
    ) -> None:
        self.adapter.set_on_speech_detected(callback)

    def open_followup(self) -> None:
        self.adapter.open_followup()

    def drain_pending(self) -> None:
        self.adapter.drain_pending()

    def remember_reply(self, text: str) -> None:
        self.last_reply_text = (text or "").strip()

    def clear_reference_buffer(self) -> None:
        if self.reference_buffer is not None:
            try:
                self.reference_buffer.clear()
            except Exception:  # noqa: BLE001
                pass

    def _is_self_speech(self, text: str) -> bool:
        if not self.self_speech_filter or not self.last_reply_text:
            return False
        ratio = difflib.SequenceMatcher(
            None,
            text.lower(),
            self.last_reply_text.lower(),
        ).ratio()
        return ratio >= self.self_speech_threshold


def _default_wake_phrases() -> tuple[str, ...]:
    from jaeger_os.plugins.whisper_stt._base import DEFAULT_WAKE_PHRASES

    return DEFAULT_WAKE_PHRASES
