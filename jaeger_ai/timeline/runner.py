"""TimelineRunner — wall-clock multi-track scheduler.

Given a :class:`Timeline`, dispatches each clip on the bus at its
``t_offset_ms`` and waits the right duration before moving on.
Per-track dispatch routes by ``track.kind``:

    animation → :class:`jaeger_os.transport.topics.AnimationCommand` on
                /act/animation
    speech    → :class:`jaeger_os.transport.topics.SpeechCommand`     on
                /act/speech

Track kinds the runner declines to dispatch (motion / light / sound)
are still SCHEDULED for timing fidelity but logged as "track kind
deferred" — they re-enable once those nodes wire up in 0.6+.

Lifecycle::

    runner = TimelineRunner(bus, timeline)
    runner.start()        # spawns a daemon thread, returns immediately
    runner.wait()         # blocks until timeline ends or stop() fires
    runner.stop()         # interrupts mid-timeline

Publishes :class:`jaeger_os.transport.topics.TimelineProgress` events:
- ``state="running"`` at t=0
- ``state="complete"`` at natural end
- ``state="interrupted"`` when stop() is called or a clip publish
  raises
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from jaeger_os.transport import topics
from jaeger_ai.timeline.schema import (
    TRACK_ANIMATION,
    TRACK_SPEECH,
    Timeline,
    TimelineClip,
)
from jaeger_os.transport import Bus


@dataclass(frozen=True)
class _ScheduledEvent:
    """One clip flattened into a sortable schedule entry."""

    t_ms: int
    track_kind: str
    clip: TimelineClip


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
                ))
        events.sort(key=lambda e: e.t_ms)
        return events

    def _run(self) -> None:
        try:
            self._started_at = time.perf_counter()
            self._publish_progress("running", elapsed_ms=0)
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
            self._dispatch_animation(event.clip)
        elif event.track_kind == TRACK_SPEECH:
            self._dispatch_speech(event.clip)
        # Other track kinds (sound / motion / light) are SCHEDULED
        # for timing fidelity but not dispatched until their nodes
        # are wired.  Silently skip rather than raise — the
        # operator's authored timeline is allowed to be
        # forward-looking.

    def _dispatch_animation(self, clip: TimelineClip) -> None:
        payload = clip.payload or {}
        self.bus.publish(topics.AnimationCommand(
            adapter=str(payload.get("adapter", "image")),
            asset_path=str(payload.get("asset", payload.get("asset_path", ""))),
            duration_ms=int(clip.duration_ms),
            params=dict(payload.get("params", {})),
            node_id=self.node_id,
        ))

    def _dispatch_speech(self, clip: TimelineClip) -> None:
        payload = clip.payload or {}
        self.bus.publish(topics.SpeechCommand(
            text=str(payload.get("text", "")),
            voice=str(payload.get("voice", "af_heart")),
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
    :class:`jaeger_os.transport.topics.TimelineCommand.timeline_json`).

    Returns the validated :class:`Timeline` or raises
    ``msgspec.ValidationError``."""
    import msgspec
    return msgspec.json.decode(payload.encode("utf-8"), type=Timeline)
