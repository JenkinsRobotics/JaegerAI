"""Timeline — multi-track scheduling for agent performances.

See ``dev/docs/avatar/0.5.0_timeline_schema.md`` for the schema design.

Public surface:

    from jaeger_os.timeline import (
        Timeline, TimelineTrack, TimelineClip,
        load_timeline, save_timeline,
    )

Runner ties to the bus separately so the schema module stays
test-friendly and tool-friendly without a live Bus.
"""

from .runner import TimelineRunner, parse_timeline_json
from .schema import (
    Timeline,
    TimelineClip,
    TimelineTrack,
    load_timeline,
    save_timeline,
)

__all__ = [
    "Timeline",
    "TimelineClip",
    "TimelineTrack",
    "TimelineRunner",
    "load_timeline",
    "parse_timeline_json",
    "save_timeline",
]
