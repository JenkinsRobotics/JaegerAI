"""Full-duplex voice bridge connecting STT -> AmbientSpeechGate -> Responder -> LLMSpeechGate -> TTS.

Designed to satisfy Directive §13's 10-turn voice exchange + mid-speech barge-in
acceptance test plus VoiceLLM's self-speech echo filter, LLM ``<ignore>``/``<reply>``
gating, mutual farewell detection, and follow-up chime hooks while remaining 100%
testable with either live hardware or injected callbacks.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .presence import (
    AmbientSpeechGate,
    GateDecision,
    LLMSpeechGate,
    RealtimeVoiceSession,
    is_farewell,
)


class FullDuplexVoiceBridge:
    """Coordinates continuous room listening, echo rejection, LLM gating, and barge-in."""

    def __init__(
        self,
        *,
        responder: Callable[[str], str],
        on_tts_start: Callable[[str], None] | None = None,
        on_tts_cancel: Callable[[str], None] | None = None,
        on_chime: Callable[[str], None] | None = None,
        session: RealtimeVoiceSession | None = None,
        use_llm_gate: bool = True,
    ) -> None:
        self._responder = responder
        self._on_tts_start = on_tts_start
        self._on_tts_cancel = on_tts_cancel
        self._use_llm_gate = bool(use_llm_gate)
        self._cancelled_turns: list[str] = []
        self._lock = threading.RLock()
        self.session = session or RealtimeVoiceSession(
            gate=AmbientSpeechGate(),
            on_barge_in=self._handle_barge_in,
            on_chime=on_chime,
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
        now: float | None = None,
    ) -> dict[str, Any]:
        """Process one transcribed room utterance with echo filter, LLM gate, and barge-in."""
        with self._lock:
            if still_speaking:
                self.session.begin_speaking()
            decision: GateDecision = self.session.on_heard_transcript(
                transcript,
                in_active_dialog=in_active_dialog,
                now=now,
            )
            if decision.action != "reply":
                return {"action": "ignore", "decision": decision.to_dict(), "reply": ""}

            raw_reply = self._responder(decision.transcript)
            reply = raw_reply
            if self._use_llm_gate:
                llm_gate = LLMSpeechGate()
                gate_action, cleaned = llm_gate.evaluate_complete(raw_reply)
                if gate_action == "ignore":
                    self.session.note_llm_ignored()
                    return {
                        "action": "ignore",
                        "decision": GateDecision("ignore", "llm_gate_ignored", decision.transcript, 0.95).to_dict(),
                        "reply": "",
                    }
                reply = cleaned

            self.session.record_assistant_speech(reply, now=now)
            self.session.begin_speaking()
            if self._on_tts_start is not None:
                self._on_tts_start(reply)
            self.session.end_speaking()

            # Mutual farewell closes the follow-up window without chiming for more speech.
            end_of_conversation = is_farewell(decision.transcript) and is_farewell(reply)
            if end_of_conversation:
                self.session.gate.clear_followup_window()
            else:
                self.session.emit_chime("followup")

            entry = {
                "turn": len(self._history) + 1,
                "user": decision.transcript,
                "assistant": reply,
                "reason": decision.reason,
                "end_of_conversation": end_of_conversation,
            }
            self._history.append(entry)
            return {
                "action": "reply",
                "decision": decision.to_dict(),
                "reply": reply,
                "turn": entry["turn"],
                "end_of_conversation": end_of_conversation,
                "barge_in_count": self.session.snapshot()["barge_in_count"],
            }

    @property
    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)


__all__ = ["FullDuplexVoiceBridge"]
