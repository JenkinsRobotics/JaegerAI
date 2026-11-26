"""24/7 voice presence: ambient speech gate (<ignore>/<reply>) + barge-in session.

Combines VoiceLLM's ambient speech gate (deciding whether heard room audio is
addressed to Jaeger or background chatter) with AG2's barge-in cancellation so
speaking immediately interrupts active TTS playback and yields to the owner.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(slots=True)
class GateDecision:
    action: str  # "reply" | "ignore"
    reason: str
    transcript: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AmbientSpeechGate:
    """Fast local <ignore>/<reply> classifier preventing false triggers in a 24/7 room."""

    def __init__(self, *, wake_words: tuple[str, ...] = ("jaeger", "hey jaeger", "droid")) -> None:
        self._wake_re = re.compile(r"\b(" + "|".join(re.escape(w) for w in wake_words) + r")\b", re.IGNORECASE)
        self._direct_q_re = re.compile(r"^\s*(can you|could you|please|what|how|why|check|run|stop|pause)\b", re.IGNORECASE)
        self._last_interaction_at = 0.0
        self._followup_window_s = 12.0

    def mark_interaction(self, now: float | None = None) -> None:
        self._last_interaction_at = time.time() if now is None else float(now)

    def evaluate(self, transcript: str, *, in_active_dialog: bool = False, now: float | None = None) -> GateDecision:
        clean = (transcript or "").strip()
        if len(clean) < 2:
            return GateDecision("ignore", "empty_or_noise", clean, 0.99)
        if self._wake_re.search(clean):
            self.mark_interaction(now)
            return GateDecision("reply", "wake_word_matched", clean, 0.98)
        ts = time.time() if now is None else float(now)
        if in_active_dialog or (ts - self._last_interaction_at) <= self._followup_window_s:
            self.mark_interaction(ts)
            return GateDecision("reply", "active_followup_window", clean, 0.85)
        if self._direct_q_re.search(clean) and clean.endswith("?"):
            return GateDecision("ignore", "unaddressed_room_question", clean, 0.7)
        return GateDecision("ignore", "background_speech", clean, 0.9)


class RealtimeVoiceSession:
    """Manages 24/7 voice presence state, barge-in cancellation, and TTS viseme hooks."""

    def __init__(
        self,
        *,
        gate: AmbientSpeechGate | None = None,
        on_barge_in: Callable[[str], None] | None = None,
    ) -> None:
        self.gate = gate or AmbientSpeechGate()
        self._on_barge_in = on_barge_in
        self._lock = threading.RLock()
        self._speaking = False
        self._listening = True
        self._barge_in_count = 0
        self._utterances_replied = 0
        self._utterances_ignored = 0
        self._last_transcript = ""

    def begin_speaking(self) -> None:
        with self._lock:
            self._speaking = True

    def end_speaking(self) -> None:
        with self._lock:
            self._speaking = False

    def on_heard_transcript(self, transcript: str, *, in_active_dialog: bool = False) -> GateDecision:
        with self._lock:
            was_speaking = self._speaking
            decision = self.gate.evaluate(transcript, in_active_dialog=in_active_dialog or was_speaking)
            self._last_transcript = decision.transcript
            if decision.action == "reply":
                self._utterances_replied += 1
                if was_speaking:
                    self._speaking = False
                    self._barge_in_count += 1
                    if self._on_barge_in is not None:
                        self._on_barge_in(decision.transcript)
            else:
                self._utterances_ignored += 1
            return decision

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "listening": self._listening,
                "speaking": self._speaking,
                "barge_in_count": self._barge_in_count,
                "utterances_replied": self._utterances_replied,
                "utterances_ignored": self._utterances_ignored,
                "last_transcript": self._last_transcript,
            }


__all__ = ["AmbientSpeechGate", "GateDecision", "RealtimeVoiceSession"]
