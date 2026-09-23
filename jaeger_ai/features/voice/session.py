"""One spoken conversation with the resident Entity.

    microphone → speech detection → STT      (stt slot, or a stand-in listener)
               → Gateway → Entity → cognition (the same path as a typed turn)
               → reply → TTS → speaker         (tts slot, or printed text)

Voice is a way into Jaeger, not a second Jaeger. There is no model, prompt,
memory or tool list in this file: the Entity chooses all of those, exactly
as it does for the WebUI. A voice turn is a Gateway turn on a ``voice``
session; the Entity, its memory and its run history are shared.

Failure degrades toward text, never toward a different mind: no TTS prints
the reply; a Gateway that cannot be reached is reported and the loop keeps
listening; nothing here can stop the Entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Protocol
import uuid

from jaeger_ai.core.gateway.client import GatewayTurnClient, GatewayUnavailable, TurnResult


class Listener(Protocol):
    """The subset of ``jaeger_os.core.audio.STTAdapter`` a session drives."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def next_phrase(self, timeout: float | None = 1.0) -> str | None: ...
    def set_paused(self, paused: bool) -> None: ...
    def set_on_speech_detected(self, callback: Callable[[], None] | None) -> None: ...


class Speaker(Protocol):
    def speak(self, text: str) -> Any: ...


class PrintSpeaker:
    """Spoken output unavailable: show the reply instead."""

    def __init__(self, write: Callable[[str], None] = print) -> None:
        self._write = write

    def speak(self, text: str) -> dict[str, Any]:
        self._write(f"jaeger> {text}")
        return {"spoken": False}


@dataclass
class VoiceTurn:
    """What one spoken exchange did, with measured timings (epoch seconds)."""

    transcript: str
    result: TurnResult | None
    spoken: bool
    error: str | None = None
    timing: dict[str, float] = field(default_factory=dict)

    def latencies_ms(self) -> dict[str, float]:
        t = self.timing

        def span(a: str, b: str) -> float | None:
            return round((t[b] - t[a]) * 1000, 1) if a in t and b in t else None

        spans = {
            "speech_end_to_transcript": span("speech_end", "transcript_ready"),
            "transcript_to_submitted": span("transcript_ready", "submitted"),
            "entity_turn": span("submitted", "reply_ready"),
            "reply_to_tts_start": span("reply_ready", "tts_start"),
            # speak() may synthesize or only print text before returning. Its
            # invocation is not evidence that a device has produced sound.
            "tts_call": span("tts_start", "tts_end"),
            "speech_end_to_tts_call": span("speech_end", "tts_start"),
            "tts_playback": span("first_audio", "playback_end"),
            "speech_end_to_first_audio": span("speech_end", "first_audio"),
        }
        return {k: v for k, v in spans.items() if v is not None}


class VoiceSession:
    """Run spoken turns against the Entity through the Gateway."""

    def __init__(
        self,
        listener: Listener,
        speaker: Speaker | None = None,
        *,
        gateway: GatewayTurnClient | None = None,
        session_id: str | None = None,
        turn_timeout_s: float = 600.0,
        on_turn: Callable[[VoiceTurn], None] | None = None,
    ) -> None:
        self.listener = listener
        self.speaker = speaker or PrintSpeaker()
        self.gateway = gateway or GatewayTurnClient()
        self.session_id = session_id or f"voice-{uuid.uuid4().hex[:12]}"
        self.turn_timeout_s = turn_timeout_s
        self.on_turn = on_turn
        self._barge_in = threading.Event()

    def open(self) -> str:
        """Attach to the Entity. Returns its id; raises if the Gateway is down."""
        entity_id = self.gateway.entity_id()
        self.gateway.ensure_session(self.session_id, title="Voice", source="voice")
        self.listener.set_on_speech_detected(self._on_speech_detected)
        self.listener.start()
        return entity_id

    def close(self) -> None:
        self.listener.set_on_speech_detected(None)
        self.listener.stop()

    def _on_speech_detected(self) -> None:
        # Barge-in: the operator started talking. A speaker that can stop
        # (Kokoro's play_async/stop) is interrupted; a blocking one finishes.
        self._barge_in.set()
        stop = getattr(self.speaker, "stop", None)
        if callable(stop) and getattr(self.speaker, "is_playing", lambda: False)():
            stop()

    def step(self, timeout: float | None = 1.0) -> VoiceTurn | None:
        """Listen for one phrase and answer it. ``None`` when nothing was said."""
        phrase = self.listener.next_phrase(timeout=timeout)
        if phrase is None or not phrase.strip():
            return None
        timing = dict(getattr(self.listener, "last_timing", {}) or {})
        timing.setdefault("transcript_ready", time.time())
        turn = VoiceTurn(transcript=phrase.strip(), result=None, spoken=False, timing=timing)

        timing["submitted"] = time.time()
        try:
            result = self.gateway.turn(self.session_id, turn.transcript, timeout_s=self.turn_timeout_s)
        except GatewayUnavailable as exc:
            turn.error = f"Jaeger is not reachable: {exc}"
            self._emit(turn)
            return turn
        timing["reply_ready"] = time.time()
        turn.result = result
        reply = result.text if result.ok else (result.error or f"turn {result.status}")
        if not result.ok:
            turn.error = reply

        self._barge_in.clear()
        self.listener.set_paused(True)
        try:
            timing["tts_start"] = time.time()
            outcome = self.speaker.speak(_speakable(reply))
            timing["tts_end"] = time.time()
            turn.spoken = bool((outcome or {}).get("spoken", True)) if isinstance(outcome, dict) else True
        except Exception as exc:  # noqa: BLE001 — a dead speaker must not end the conversation
            timing.pop("tts_start", None)
            turn.error = f"speech output failed ({exc}); reply: {reply}"
            PrintSpeaker().speak(reply)
        finally:
            self.listener.set_paused(False)
        if self._barge_in.is_set():
            timing["barge_in"] = time.time()
        self._emit(turn)
        return turn

    def _emit(self, turn: VoiceTurn) -> None:
        if self.on_turn is not None:
            self.on_turn(turn)


def _speakable(text: str) -> str:
    from jaeger_os.core.voice import clean_voice_reply

    return clean_voice_reply(text) or text
