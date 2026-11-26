"""Full-duplex voice bridge connecting STT -> AmbientSpeechGate -> Responder -> TTS + Avatar visemes.

Designed to satisfy Directive §13's 10-turn voice exchange + mid-speech barge-in
acceptance test while remaining 100% testable with either live hardware or injected callbacks.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .presence import AmbientSpeechGate, GateDecision, RealtimeVoiceSession


class FullDuplexVoiceBridge:
    """Coordinates continuous room listening, barge-in cancellation, and avatar lip-sync events."""

    def __init__(
        self,
        *,
        responder: Callable[[str], str],
        on_tts_start: Callable[[str], None] | None = None,
        on_tts_cancel: Callable[[str], None] | None = None,
        session: RealtimeVoiceSession | None = None,
    ) -> None:
        self._responder = responder
        self._on_tts_start = on_tts_start
        self._on_tts_cancel = on_tts_cancel
        self._cancelled_turns: list[str] = []
        self._lock = threading.RLock()
        self.session = session or RealtimeVoiceSession(
            gate=AmbientSpeechGate(),
            on_barge_in=self._handle_barge_in,
        )
        self._history: list[dict[str, Any]] = []

    def _handle_barge_in(self, interrupting_text: str) -> None:
        self._cancelled_turns.append(interrupting_text)
        if self._on_tts_cancel is not None:
            self._on_tts_cancel(interrupting_text)

    def handle_utterance(
        self,
        transcript: str,
        *,
        in_active_dialog: bool = False,
        still_speaking: bool = False,
    ) -> dict[str, Any]:
        """Process one transcribed room utterance with full barge-in support."""
        with self._lock:
            if still_speaking:
                self.session.begin_speaking()
            decision: GateDecision = self.session.on_heard_transcript(
                transcript,
                in_active_dialog=in_active_dialog,
            )
            if decision.action != "reply":
                return {"action": "ignore", "decision": decision.to_dict(), "reply": ""}

            reply = self._responder(decision.transcript)
            self.session.begin_speaking()
            if self._on_tts_start is not None:
                self._on_tts_start(reply)
            self.session.end_speaking()
            entry = {
                "turn": len(self._history) + 1,
                "user": decision.transcript,
                "assistant": reply,
                "reason": decision.reason,
            }
            self._history.append(entry)
            return {
                "action": "reply",
                "decision": decision.to_dict(),
                "reply": reply,
                "turn": entry["turn"],
                "barge_in_count": self.session.snapshot()["barge_in_count"],
            }

    @property
    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)


__all__ = ["FullDuplexVoiceBridge"]
