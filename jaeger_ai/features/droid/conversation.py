"""Incremental, resumable speech control for Droid mode.

Speech-floor ownership is separate from task execution. A brief backchannel
may pause playback without cancelling the Gateway turn, while an explicit
stop still takes effect immediately. The controller also records what was
actually delivered instead of treating generated text as heard speech.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum
import re
import time
import uuid
from typing import Callable


class InterruptionKind(StrEnum):
    BACKCHANNEL = "backchannel"
    CORRECTION = "correction"
    QUESTION = "question"
    TAKEOVER = "takeover"
    STOP = "stop"
    REFINEMENT = "refinement"


@dataclass(frozen=True)
class InterruptionDecision:
    kind: InterruptionKind
    resume: bool
    route_to_agent: bool
    cancel_task: bool = False


@dataclass
class SpeechUnit:
    id: str
    text: str
    source_id: str | None
    state: str = "queued"
    queued_at: float = 0.0
    started_at: float | None = None
    delivered_at: float | None = None
    interrupted_at: float | None = None
    attempts: int = 0


_BACKCHANNEL = re.compile(
    r"^(?:m+h+m+|uh[ -]?huh|mm[ -]?hmm|yeah|yep|yes|okay|ok|right|sure|got it|i see|go on|continue)[.! ]*$",
    re.I,
)
_STOP = re.compile(
    r"^(?:stop|stop talking|be quiet|hush|mute|cancel|never ?mind|camera off|mic off|stop moving)[.! ]*$",
    re.I,
)
_TAKEOVER = re.compile(
    r"^(?:hold on|wait|one moment|let me (?:finish|talk|explain|think)|don'?t interrupt|i(?:'m| am) not (?:done|finished))[.! ]*$",
    re.I,
)
_CORRECTION = re.compile(r"^(?:no[, ]|actually\b|i mean\b|rather\b|correction\b|not that\b)", re.I)
_QUESTION = re.compile(r"^(?:who|what|when|where|why|how|which|can|could|would|do|does|did|is|are|was|were)\b", re.I)


def classify_interruption(text: str) -> InterruptionDecision:
    """Classify a completed overlap without an LLM or speculative intent."""
    clean = " ".join((text or "").strip().split())
    if _STOP.fullmatch(clean):
        task = clean.lower() in {"stop moving", "camera off", "mic off", "cancel"}
        return InterruptionDecision(InterruptionKind.STOP, False, task, task)
    if _TAKEOVER.fullmatch(clean):
        return InterruptionDecision(InterruptionKind.TAKEOVER, False, False)
    if _BACKCHANNEL.fullmatch(clean):
        return InterruptionDecision(InterruptionKind.BACKCHANNEL, True, False)
    if _CORRECTION.match(clean):
        return InterruptionDecision(InterruptionKind.CORRECTION, False, True)
    if clean.endswith("?") or _QUESTION.match(clean):
        return InterruptionDecision(InterruptionKind.QUESTION, False, True)
    return InterruptionDecision(InterruptionKind.REFINEMENT, False, True)


class SpeechPlanController:
    """Serialize speech units and make interruption recovery deterministic."""

    def __init__(self, send: Callable[[SpeechUnit], None], stop: Callable[[], None], *, ledger_size: int = 100):
        self._send = send
        self._stop = stop
        self._pending: deque[SpeechUnit] = deque()
        self._current: SpeechUnit | None = None
        self._paused: SpeechUnit | None = None
        self._blocked_sources: set[str] = set()
        self.ledger: deque[SpeechUnit] = deque(maxlen=ledger_size)

    @property
    def speaking(self) -> bool:
        return self._current is not None

    @property
    def paused(self) -> bool:
        return self._paused is not None

    def enqueue(self, text: str, *, source_id: str | None = None) -> bool:
        clean = " ".join((text or "").strip().split())
        if not clean or (source_id and source_id in self._blocked_sources):
            return False
        unit = SpeechUnit(uuid.uuid4().hex, clean, source_id, queued_at=time.time())
        self._pending.append(unit)
        self._dispatch()
        return True

    def playback_started(self) -> None:
        if self._current:
            self._current.state = "speaking"
            self._current.started_at = time.time()

    def playback_finished(self) -> None:
        if not self._current:
            return
        unit, self._current = self._current, None
        unit.state = "delivered"
        unit.delivered_at = time.time()
        self.ledger.append(unit)
        self._dispatch()

    def pause_for_overlap(self) -> bool:
        if not self._current:
            return False
        unit, self._current = self._current, None
        unit.state = "paused"
        unit.interrupted_at = time.time()
        self._paused = unit
        self._stop()
        return True

    def resolve(self, text: str) -> InterruptionDecision:
        decision = classify_interruption(text)
        paused, self._paused = self._paused, None
        if paused is not None:
            if decision.resume:
                paused.state = "queued"
                self._pending.appendleft(paused)
            else:
                paused.state = "interrupted"
                self.ledger.append(paused)
                self._discard_source(paused.source_id)
                if paused.source_id and decision.route_to_agent:
                    self._blocked_sources.add(paused.source_id)
        self._dispatch()
        return decision

    def unblock_source(self, source_id: str | None) -> None:
        if source_id:
            self._blocked_sources.discard(source_id)

    def abandon(self, *, source_id: str | None = None) -> None:
        self._stop()
        for unit in (self._current, self._paused):
            if unit is not None and (source_id is None or unit.source_id == source_id):
                unit.state = "interrupted"
                unit.interrupted_at = unit.interrupted_at or time.time()
                self.ledger.append(unit)
        self._current = None
        self._paused = None
        if source_id is None:
            self._pending.clear()
        else:
            self._discard_source(source_id)

    def snapshot(self) -> dict:
        return {
            "state": "paused" if self.paused else "speaking" if self.speaking else "idle",
            "current": asdict(self._current) if self._current else None,
            "paused": asdict(self._paused) if self._paused else None,
            "queued": [asdict(unit) for unit in self._pending],
            "delivered": [asdict(unit) for unit in self.ledger],
        }

    def _discard_source(self, source_id: str | None) -> None:
        if source_id is not None:
            self._pending = deque(unit for unit in self._pending if unit.source_id != source_id)

    def _dispatch(self) -> None:
        if self._current is not None or self._paused is not None:
            return
        while self._pending:
            unit = self._pending.popleft()
            if unit.source_id and unit.source_id in self._blocked_sources:
                continue
            self._current = unit
            unit.attempts += 1
            unit.state = "queued_for_playback"
            self._send(unit)
            return
