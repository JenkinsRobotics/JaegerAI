"""24/7 voice presence: ambient speech gate (<ignore>/<reply>), self-speech echo filter & barge-in.

Combines VoiceLLM's layered always-listening voice pipeline:
  - Hallucination drop (Whisper bracketed artifacts like ``[BLANK_AUDIO]``, ``(clicking)``)
  - Layer C self-speech similarity rejection (``SelfSpeechFilter``)
  - Layer D streaming LLM speech gate (``LLMSpeechGate`` parsing ``<ignore>`` / ``<reply>``)
  - Mutual farewell detection to avoid soliciting ambient noise after goodbye
  - Barge-in cancellation so speaking interrupts active TTS playback immediately
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import re
import threading
import time
from typing import Any, Callable


# Whisper hallucinates bracketed sound descriptions on noise/silence.
_HALLUCINATION_RE = re.compile(r"^\s*[\[\(\*♪].*[\]\)\*♪]\s*$")

_GATE_TAG_RE = re.compile(r"<\s*(ignore|reply)\s*>", re.IGNORECASE)
_GATE_END_TAG_RE = re.compile(r"</\s*(?:reply|ignore)\s*>", re.IGNORECASE)
_MAX_GATE_END_TAG_LEN = len("</ignore>")

_FAREWELL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:good\s*night|goodnight|goodbye|bye(?:\s+bye)?|see\s+ya|see\s+you\s+later|talk\s+to\s+you\s+later|catch\s+you\s+later|signing\s+off)\b", re.IGNORECASE),
)


def is_hallucination(text: str) -> bool:
    """Return True if *text* looks like a Whisper silence/noise hallucination."""
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    return bool(_HALLUCINATION_RE.match(cleaned))


def is_farewell(text: str) -> bool:
    """Return True if *text* contains an explicit farewell phrase."""
    cleaned = (text or "").strip()
    return bool(cleaned) and any(p.search(cleaned) for p in _FAREWELL_PATTERNS)


def strip_gate_tags(text: str) -> str:
    """Remove any ``<reply>``, ``<ignore>``, ``</reply>``, or ``</ignore>`` tags from text."""
    out = _GATE_TAG_RE.sub("", text or "")
    out = _GATE_END_TAG_RE.sub("", out)
    return out.strip()


@dataclass(slots=True)
class EchoCheckResult:
    is_echo: bool
    similarity: float
    reason: str
    matched_reply: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SelfSpeechFilter:
    """Layer C self-speech rejection comparing mic transcripts against recent TTS output.

    Prevents the assistant from replying to its own acoustic bleed through the speakers
    even when hardware AEC is unavailable or leaks a tail fragment.
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.75,
        window_s: float = 20.0,
        max_history: int = 4,
        min_substring_chars: int = 12,
    ) -> None:
        self._threshold = max(0.3, min(1.0, float(similarity_threshold)))
        self._window_s = max(1.0, float(window_s))
        self._min_sub = max(6, int(min_substring_chars))
        self._recent: deque[tuple[float, str]] = deque(maxlen=max(1, int(max_history)))
        self._lock = threading.RLock()

    @staticmethod
    def _normalize(text: str) -> str:
        words = re.findall(r"[a-z0-9']+", (text or "").lower())
        return " ".join(words)

    def record_assistant_reply(self, text: str, *, now: float | None = None) -> None:
        norm = self._normalize(strip_gate_tags(text))
        if not norm:
            return
        ts = time.time() if now is None else float(now)
        with self._lock:
            self._recent.append((ts, norm))

    def check(self, transcript: str, *, now: float | None = None) -> EchoCheckResult:
        norm = self._normalize(transcript)
        if not norm:
            return EchoCheckResult(False, 0.0, "empty")
        ts = time.time() if now is None else float(now)
        best_ratio = 0.0
        best_reply = ""
        with self._lock:
            entries = list(self._recent)
        for reply_ts, reply_norm in reversed(entries):
            if (ts - reply_ts) > self._window_s:
                continue
            if len(norm) >= self._min_sub and norm in reply_norm:
                return EchoCheckResult(True, 1.0, "substring_of_recent_reply", reply_norm)
            ratio = SequenceMatcher(None, norm, reply_norm).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_reply = reply_norm
            if ratio >= self._threshold:
                return EchoCheckResult(True, round(ratio, 4), "similarity_threshold_exceeded", reply_norm)
        return EchoCheckResult(False, round(best_ratio, 4), "distinct_speech", best_reply)

    def clear(self) -> None:
        with self._lock:
            self._recent.clear()


class LLMSpeechGate:
    """Layer D streaming LLM-gated speech parser (``<ignore>`` vs ``<reply>``).

    Buffers up to ``buffer_chars`` of streaming LLM output until a leading
    ``<ignore>`` or ``<reply>`` tag arrives:
      - ``<ignore>`` suppresses all TTS output for the turn.
      - ``<reply>`` forwards the post-tag tail while stripping any closing tag.
      - If the model omits tags beyond ``buffer_chars`` (or finishes early), falls back
        safely to ``reply`` so valid answers are never lost in silence.
    """

    SYSTEM_PROMPT_HINT = (
        "Start every live voice response with either <reply> if the user is addressing you "
        "or <ignore> if the transcript is background chatter, TV audio, or noise."
    )

    def __init__(self, *, buffer_chars: int = 24) -> None:
        self._buffer_chars = max(10, int(buffer_chars))
        self.reset()

    def reset(self) -> None:
        self._gate_buf = ""
        self._tail_buf = ""
        self._decided = False
        self._ignored = False
        self._fallback_triggered = False

    @property
    def decided(self) -> bool:
        return self._decided

    @property
    def ignored(self) -> bool:
        return self._ignored

    @property
    def fallback_triggered(self) -> bool:
        return self._fallback_triggered

    @property
    def action(self) -> str:
        if not self._decided:
            return "pending"
        return "ignore" if self._ignored else "reply"

    def feed(self, delta: str) -> str:
        """Feed a streaming LLM token delta; returns speakable text ready for TTS."""
        if not delta:
            return ""
        if not self._decided:
            self._gate_buf += delta
            tail = self._decide_from_buffer()
            if not self._decided or self._ignored or not tail:
                return ""
            return self._emit_clean_tail(tail)
        if self._ignored:
            return ""
        return self._emit_clean_tail(delta)

    def flush(self) -> str:
        """Finalize stream; resolves short untagged outputs and drains closing-tag holdback."""
        if not self._decided and self._gate_buf:
            self._decided = True
            self._ignored = False
            self._fallback_triggered = True
            self._tail_buf += self._gate_buf
            self._gate_buf = ""
        if self._ignored:
            self._tail_buf = ""
            return ""
        out = _GATE_END_TAG_RE.sub("", self._tail_buf)
        self._tail_buf = ""
        return out

    def evaluate_complete(self, text: str) -> tuple[str, str]:
        """Convenience one-shot evaluation returning ``(action, cleaned_reply)``."""
        self.reset()
        head = self.feed(text or "")
        tail = self.flush()
        combined = (head + tail).strip()
        return self.action, ("" if self.ignored else combined)

    def _decide_from_buffer(self) -> str:
        m = _GATE_TAG_RE.search(self._gate_buf)
        if m is not None:
            tag = m.group(1).lower()
            self._decided = True
            self._ignored = tag == "ignore"
            tail = "" if self._ignored else self._gate_buf[m.end():]
            self._gate_buf = ""
            return tail
        if len(self._gate_buf) >= self._buffer_chars:
            self._decided = True
            self._ignored = False
            self._fallback_triggered = True
            tail = self._gate_buf
            self._gate_buf = ""
            return tail
        return ""

    def _emit_clean_tail(self, chunk: str) -> str:
        self._tail_buf += chunk
        self._tail_buf = _GATE_END_TAG_RE.sub("", self._tail_buf)
        if len(self._tail_buf) <= _MAX_GATE_END_TAG_LEN:
            return ""
        emit = self._tail_buf[:-_MAX_GATE_END_TAG_LEN]
        self._tail_buf = self._tail_buf[-_MAX_GATE_END_TAG_LEN:]
        return emit


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

    def __init__(
        self,
        *,
        wake_words: tuple[str, ...] = ("jaeger", "hey jaeger", "droid"),
        followup_window_s: float = 12.0,
        self_speech_filter: SelfSpeechFilter | None = None,
    ) -> None:
        self._wake_re = re.compile(r"\b(" + "|".join(re.escape(w) for w in wake_words) + r")\b", re.IGNORECASE)
        self._direct_q_re = re.compile(r"^\s*(can you|could you|please|what|how|why|check|run|stop|pause)\b", re.IGNORECASE)
        self._last_interaction_at = 0.0
        self._followup_window_s = max(1.0, float(followup_window_s))
        self.self_speech_filter = self_speech_filter or SelfSpeechFilter()

    def mark_interaction(self, now: float | None = None) -> None:
        self._last_interaction_at = time.time() if now is None else float(now)

    def clear_followup_window(self) -> None:
        self._last_interaction_at = 0.0

    def record_assistant_speech(self, text: str, *, now: float | None = None) -> None:
        self.self_speech_filter.record_assistant_reply(text, now=now)

    def evaluate(self, transcript: str, *, in_active_dialog: bool = False, now: float | None = None) -> GateDecision:
        clean = (transcript or "").strip()
        if len(clean) < 2:
            return GateDecision("ignore", "empty_or_noise", clean, 0.99)
        if is_hallucination(clean):
            return GateDecision("ignore", "whisper_hallucination", clean, 0.99)
        ts = time.time() if now is None else float(now)
        echo = self.self_speech_filter.check(clean, now=ts)
        if echo.is_echo:
            return GateDecision("ignore", f"self_speech_echo:{echo.reason}", clean, min(0.99, max(0.85, echo.similarity)))
        if self._wake_re.search(clean):
            self.mark_interaction(ts)
            return GateDecision("reply", "wake_word_matched", clean, 0.98)
        if in_active_dialog or (ts - self._last_interaction_at) <= self._followup_window_s:
            self.mark_interaction(ts)
            return GateDecision("reply", "active_followup_window", clean, 0.85)
        if self._direct_q_re.search(clean) and clean.endswith("?"):
            return GateDecision("ignore", "unaddressed_room_question", clean, 0.7)
        return GateDecision("ignore", "background_speech", clean, 0.9)


class RealtimeVoiceSession:
    """Manages 24/7 voice presence state, echo filtering, barge-in cancellation, and chime hooks."""

    def __init__(
        self,
        *,
        gate: AmbientSpeechGate | None = None,
        on_barge_in: Callable[[str], None] | None = None,
        on_chime: Callable[[str], None] | None = None,
    ) -> None:
        self.gate = gate or AmbientSpeechGate()
        self._on_barge_in = on_barge_in
        self._on_chime = on_chime
        self._lock = threading.RLock()
        self._speaking = False
        self._listening = True
        self._barge_in_count = 0
        self._utterances_replied = 0
        self._utterances_ignored = 0
        self._echo_rejected_count = 0
        self._llm_ignored_count = 0
        self._last_transcript = ""

    def emit_chime(self, kind: str) -> None:
        if self._on_chime is not None:
            self._on_chime(kind)

    def record_assistant_speech(self, text: str, *, now: float | None = None) -> None:
        with self._lock:
            self.gate.record_assistant_speech(text, now=now)

    def note_llm_ignored(self) -> None:
        with self._lock:
            self._llm_ignored_count += 1
            self._utterances_ignored += 1

    def begin_speaking(self) -> None:
        with self._lock:
            self._speaking = True

    def end_speaking(self) -> None:
        with self._lock:
            self._speaking = False

    def on_heard_transcript(
        self,
        transcript: str,
        *,
        in_active_dialog: bool = False,
        now: float | None = None,
    ) -> GateDecision:
        with self._lock:
            was_speaking = self._speaking
            decision = self.gate.evaluate(transcript, in_active_dialog=in_active_dialog or was_speaking, now=now)
            self._last_transcript = decision.transcript
            if decision.action == "reply":
                self._utterances_replied += 1
                if was_speaking:
                    self._speaking = False
                    self._barge_in_count += 1
                    self.emit_chime("barge_in")
                    if self._on_barge_in is not None:
                        self._on_barge_in(decision.transcript)
                elif decision.reason == "wake_word_matched":
                    self.emit_chime("wake")
            else:
                self._utterances_ignored += 1
                if decision.reason.startswith("self_speech_echo"):
                    self._echo_rejected_count += 1
            return decision

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "listening": self._listening,
                "speaking": self._speaking,
                "barge_in_count": self._barge_in_count,
                "utterances_replied": self._utterances_replied,
                "utterances_ignored": self._utterances_ignored,
                "echo_rejected_count": self._echo_rejected_count,
                "llm_ignored_count": self._llm_ignored_count,
                "last_transcript": self._last_transcript,
            }


__all__ = [
    "AmbientSpeechGate",
    "EchoCheckResult",
    "GateDecision",
    "LLMSpeechGate",
    "RealtimeVoiceSession",
    "SelfSpeechFilter",
    "is_farewell",
    "is_hallucination",
    "strip_gate_tags",
]
