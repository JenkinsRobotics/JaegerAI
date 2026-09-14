"""Timeline + clip + track schemas (msgspec).

A timeline is a multi-track performance: animation, speech, sound,
motion and light on one wall clock. It is the general form that a
single-channel sequencer — a motion script, a playlist — is a slice of.

These ride the bus inside :class:`TimelineCommand` as JSON and persist
to ``<instance>/timelines/<name>.json``.

Salvaged from Mochi v4 in 2026-08. The CONTRACT survived the split into
JaegerOS — ``ACT_TIMELINE_RUN``, ``TimelineCommand`` and
``TimelineProgress`` have been in ``contract/topics.py`` the whole time —
but the implementation did not come with it, so the topics were declared
and nothing on the bus could run one. This closes that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import msgspec


# Track kinds — the runner dispatches each track to a different
# bus topic based on this string.  Kept as constants so misspellings
# surface at the schema level instead of at runtime.
TRACK_ANIMATION: Final = "animation"
TRACK_SPEECH: Final = "speech"
TRACK_SOUND: Final = "sound"
TRACK_MOTION: Final = "motion"
TRACK_LIGHT: Final = "light"
#: A track of CUES rather than events: each clip names a sequence with
#: its own internal logic, played for its slot on the shared clock. This
#: is what makes a timeline compose with a sequencer instead of
#: competing with it — tracks give simultaneity, a cue gives order.
#: The scheduler does not run these itself; whoever owns the sequencer
#: does, which keeps the format from depending on one.
TRACK_SCRIPT: Final = "script"

VALID_TRACK_KINDS = frozenset({
    TRACK_ANIMATION, TRACK_SPEECH, TRACK_SOUND,
    TRACK_MOTION, TRACK_LIGHT, TRACK_SCRIPT,
})


class TimelineClip(msgspec.Struct, kw_only=True):
    """One event on a track.

    Fields
    ──────
    ``t_offset_ms``  start time in milliseconds from the track's t=0
    ``duration_ms``  how long the clip lasts; 0 means "play to natural
                     end" (image: hold until next clip; gif/video:
                     full asset duration)
    ``payload``      kind-specific data; see the schema doc for shapes
    ``label``        operator-visible name (optional, debug-friendly)
    """

    t_offset_ms: int
    duration_ms: int = 0
    payload: dict = msgspec.field(default_factory=dict)
    label: str = ""


class TimelineTrack(msgspec.Struct, kw_only=True):
    """A homogeneous clip sequence for one consumer.

    ``kind``    which consumer: animation, speech, sound, motion, light
    ``target``  WHICH ONE. Empty means "the only one" — a solo
                performance never has to say. Two characters in a scene
                need it, and so does a body with three servos or a rig
                with two displays: the kind says what a clip means, the
                target says who does it.
    ``name``    operator-visible label for an editing surface
    """

    kind: str
    target: str = ""
    name: str = ""
    clips: list[TimelineClip] = msgspec.field(default_factory=list)


class Timeline(msgspec.Struct, kw_only=True):
    """Top-level performance — multi-track schedule.

    ``name``         identifier the agent uses to play it
    ``description``  one-line operator-visible blurb
    ``duration_ms``  total runtime; 0 = max(track end times)
    ``loop``         when True, restart from t=0 after natural end
    ``tracks``       all tracks; runner publishes each clip on the
                     bus at its absolute t_offset_ms
    """

    name: str
    description: str = ""
    duration_ms: int = 0
    loop: bool = False
    tracks: list[TimelineTrack] = msgspec.field(default_factory=list)
    schema_version: int = 1

    def computed_duration_ms(self) -> int:
        """Return ``duration_ms`` when set, otherwise the max of all
        track-end times."""
        if self.duration_ms:
            return self.duration_ms
        ends = (
            (c.t_offset_ms + c.duration_ms)
            for t in self.tracks for c in t.clips
        )
        return max(ends, default=0)


# ── load / save ────────────────────────────────────────────────────

def load_timeline(path: Path) -> Timeline:
    """Read a Timeline JSON from disk.  Raises ``msgspec.ValidationError``
    on schema mismatch — operator gets a precise error rather than a
    half-loaded broken timeline."""
    data = path.read_bytes()
    return msgspec.json.decode(data, type=Timeline)


def save_timeline(timeline: Timeline, path: Path) -> None:
    """Atomic JSON write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(msgspec.json.encode(timeline))
    tmp.replace(path)
