"""TimelineRunner — wall-clock multi-track scheduler.

Given a :class:`Timeline`, dispatches each clip on the bus at its
``t_offset_ms`` and waits the right duration before moving on.
Per-track dispatch routes by ``track.kind``:

    animation → :class:`DisplayCommand` on /act/display/play
    speech    → :class:`SpeechCommand`  on /act/speech/say

Track kinds the runner declines to dispatch (motion / light / sound)
are still SCHEDULED for timing fidelity but logged as "track kind
deferred" — they re-enable once those nodes wire up in 0.6+.

Lifecycle::

    runner = TimelineRunner(bus, timeline)
    runner.start()        # spawns a daemon thread, returns immediately
    runner.wait()         # blocks until timeline ends or stop() fires
    runner.stop()         # interrupts mid-timeline

Publishes :class:`TimelineProgress` events:
- ``state="running"`` at t=0
- ``state="complete"`` at natural end
- ``state="interrupted"`` when stop() is called or a clip publish
  raises
"""

from __future__ import annotations

import json
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Any

from jaeger_os.contract import topics
from jaeger_os.transport import Bus

from .schema import (
    TRACK_ANIMATION,
    TRACK_SPEECH,
    Timeline,
    TimelineClip,
)

#: What this scheduler actually sends somewhere. The schema declares
#: more kinds than this ON PURPOSE — a track kind exists so a consumer
#: the scheduler has never heard of can own it — but the difference
#: between "declared" and "dispatched" has to be visible, and it was
#: not: a lighting cue that controls nothing looked exactly like one
#: that works.
DISPATCHED: frozenset = frozenset({TRACK_ANIMATION, TRACK_SPEECH})


@dataclass(frozen=True)
class _ScheduledEvent:
    """One clip flattened into a sortable schedule entry."""

    t_ms: int
    track_kind: str
    clip: TimelineClip
    target: str = ""


class TimelineRunner:
    """Schedule a :class:`Timeline`'s clips on the bus."""

    def __init__(
        self,
        bus: Bus,
        timeline: Timeline,
        *,
        node_id: str = "timeline_runner",
    ) -> None:
        self.bus = bus
        self.timeline = timeline
        self.node_id = node_id
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._done_event = threading.Event()
        self._started_at: float = 0.0
        self._final_state: str = ""

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the scheduler thread.  Returns immediately."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"timeline:{self.timeline.name}",
            daemon=True,
        )
        self._stop_event.clear()
        self._done_event.clear()
        self._thread.start()

    def stop(self) -> None:
        """Interrupt mid-timeline; runner exits and publishes the
        ``interrupted`` TimelineProgress event."""
        self._stop_event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the runner finishes or ``timeout`` elapses.
        Returns ``True`` if finished, ``False`` if still running."""
        return self._done_event.wait(timeout=timeout)

    @property
    def finished(self) -> bool:
        return self._done_event.is_set()

    @property
    def final_state(self) -> str:
        return self._final_state

    # ── scheduling ────────────────────────────────────────────────

    def _build_schedule(self) -> list[_ScheduledEvent]:
        events: list[_ScheduledEvent] = []
        for track in self.timeline.tracks:
            for clip in track.clips:
                events.append(_ScheduledEvent(
                    t_ms=int(clip.t_offset_ms),
                    track_kind=track.kind,
                    clip=clip,
                    target=getattr(track, "target", "") or "",
                ))
        events.sort(key=lambda e: e.t_ms)
        return events

    def _run(self) -> None:
        try:
            self._started_at = time.perf_counter()
            self._publish_progress("running", elapsed_ms=0)
            skipped = self.unsupported()
            if skipped:
                # State `partial`, so a UI can colour it differently
                # from a clean run without parsing a message.
                self._publish_progress("partial", elapsed_ms=0)
                warnings.warn(
                    "%s: %d track(s) scheduled but not dispatched — no node "
                    "handles them: %s" % (
                        self.timeline.name, len(skipped),
                        ", ".join(f"{name} ({kind})" for name, kind in skipped)),
                    RuntimeWarning, stacklevel=2)
            schedule = self._build_schedule()
            total_ms = self.timeline.computed_duration_ms()
            for event in schedule:
                if not self._wait_until(event.t_ms):
                    self._final_state = "interrupted"
                    self._publish_progress(
                        "interrupted",
                        elapsed_ms=self._elapsed_ms(),
                    )
                    return
                try:
                    self._dispatch(event)
                except Exception:  # noqa: BLE001
                    self._final_state = "interrupted"
                    self._publish_progress(
                        "interrupted",
                        elapsed_ms=self._elapsed_ms(),
                    )
                    return
            # Hold until the timeline's nominal end time before
            # publishing "complete" — gives consumers a clean signal.
            if total_ms > 0:
                self._wait_until(total_ms)
            self._final_state = "complete"
            self._publish_progress(
                "complete",
                elapsed_ms=self._elapsed_ms(),
                duration_ms=total_ms,
            )
        finally:
            self._done_event.set()

    def unsupported(self) -> list[tuple[str, str]]:
        """(track name, kind) for every track this runner cannot play.

        The timeline SCHEMA accepts sound, motion, light and script;
        this scheduler dispatches animation and speech. The difference
        is a real gap and an operator has to be able to see it without
        reading the source.
        """
        return [(track.name or track.kind, track.kind)
                for track in self.timeline.tracks
                if track.kind not in DISPATCHED and track.clips]

    def _wait_until(self, target_ms: int) -> bool:
        """Sleep until ``target_ms`` elapsed since start.  Returns
        ``False`` if a stop was requested mid-wait."""
        now_ms = self._elapsed_ms()
        delay_ms = target_ms - now_ms
        if delay_ms <= 0:
            return not self._stop_event.is_set()
        interrupted = self._stop_event.wait(timeout=delay_ms / 1000.0)
        return not interrupted

    def _elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._started_at) * 1000.0)

    # ── per-track dispatch ────────────────────────────────────────

    def _dispatch(self, event: _ScheduledEvent) -> None:
        if event.track_kind == TRACK_ANIMATION:
            self._dispatch_animation(event.clip, event.target)
        elif event.track_kind == TRACK_SPEECH:
            self._dispatch_speech(event.clip, event.target)
        # Everything else is SCHEDULED for timing fidelity and not
        # dispatched, because no node has claimed it yet. Skipping is
        # right — an authored timeline is allowed to be forward-looking
        # — but skipping SILENTLY is not: it made a lighting cue that
        # controls nothing indistinguishable from one that works, and
        # the only way to find out was to watch the lamp.
        #
        # Reported once at start by `unsupported()`, not per event: a
        # warning per clip is a warning nobody reads.

    def _dispatch_animation(self, clip: TimelineClip, target: str = "") -> None:
        payload = clip.payload or {}
        # DisplayCommand, not v4's AnimationCommand — the display
        # topic is what the contract carries now, and "auto" lets the
        # engine pick the decoder by extension rather than making a
        # timeline author name one.
        self.bus.publish(topics.DisplayCommand(
            adapter=str(payload.get("adapter", "auto")),
            asset_path=str(payload.get("asset", payload.get("asset_path", ""))),
            duration_ms=int(clip.duration_ms),
            params=dict(payload.get("params", {})),
            node_id=target or self.node_id,
        ))

    def _dispatch_speech(self, clip: TimelineClip, target: str = "") -> None:
        payload = clip.payload or {}
        # A track's target names WHO speaks — a character id, not a
        # voice id. Resolving one to the other needs the character pack,
        # which this package deliberately knows nothing about, so an
        # unset voice stays EMPTY and means "the module default".
        # Filling it with the target was a bug: it sent a character
        # name to a synthesiser expecting a voice.
        # An empty voice means "the module's configured default" —
        # naming one here would override every character's own voice
        # from inside a timeline that has no opinion about it.
        self.bus.publish(topics.SpeechCommand(
            text=str(payload.get("text", "")),
            voice=str(payload.get("voice", "")),
            node_id=self.node_id,
        ))

    # ── progress publishing ───────────────────────────────────────

    def _publish_progress(
        self,
        state: str,
        *,
        elapsed_ms: int,
        duration_ms: int = 0,
    ) -> None:
        try:
            self.bus.publish(topics.TimelineProgress(
                timeline_name=self.timeline.name,
                state=state,
                elapsed_ms=elapsed_ms,
                duration_ms=duration_ms,
                node_id=self.node_id,
            ))
        except Exception:  # noqa: BLE001
            pass


# ── inline-JSON convenience ───────────────────────────────────────

def parse_timeline_json(payload: str) -> Timeline:
    """Parse a Timeline from inline JSON (the wire format used by
    :class:`TimelineCommand.timeline_json`).

    Returns the validated :class:`Timeline` or raises
    ``msgspec.ValidationError``."""
    import msgspec
    return msgspec.json.decode(payload.encode("utf-8"), type=Timeline)
