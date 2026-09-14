"""jaeger_os.timeline — multi-track scheduling on the bus.

A timeline is a performance: animation, speech, sound, motion and light
laid on one wall clock, each track dispatched to the node that consumes
it. It is the GENERAL form — a motion script is one channel of it, a
playlist is one channel of it — which is why it lives beside the bus
rather than inside any engine that happens to be one of its consumers.

    from jaeger_os.timeline import (
        Timeline, TimelineTrack, TimelineClip,
        TimelineRunner, load_timeline, save_timeline, parse_timeline_json,
    )

The runner ties to the bus; the schema does not. That split is
deliberate — authoring tools, validators and tests can read and write
timelines without a live Bus.

WHERE THIS CAME FROM. Salvaged from Mochi v4, 2026-08. The contract for
it has been in ``contract/topics.py`` since the split — ``ACT_TIMELINE_RUN``,
``TimelineCommand``, ``TimelineProgress`` — but the implementation was
left behind in the archive, so the topics were declared and nothing
could run one. Two track kinds dispatch today (animation, speech);
sound, motion and light are SCHEDULED for timing fidelity and skipped,
so a forward-looking timeline keeps correct time on the tracks that do
exist.
"""

from .runner import TimelineRunner, parse_timeline_json
from .schema import (
    TRACK_ANIMATION,
    TRACK_LIGHT,
    TRACK_MOTION,
    TRACK_SCRIPT,
    TRACK_SOUND,
    TRACK_SPEECH,
    VALID_TRACK_KINDS,
    Timeline,
    TimelineClip,
    TimelineTrack,
    load_timeline,
    save_timeline,
)

__all__ = [
    "Timeline",
    "TimelineTrack",
    "TimelineClip",
    "TimelineRunner",
    "load_timeline",
    "save_timeline",
    "parse_timeline_json",
    "TRACK_ANIMATION",
    "TRACK_SPEECH",
    "TRACK_SOUND",
    "TRACK_MOTION",
    "TRACK_LIGHT",
    "TRACK_SCRIPT",
    "VALID_TRACK_KINDS",
]
