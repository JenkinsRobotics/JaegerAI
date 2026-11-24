"""jaeger-events: replay-safe EventBus, StreamingDeltaBatcher, and non-blocking TelemetryEmitter."""

from .batcher import StreamingDeltaBatcher
from .bus import EventBus, is_replaying, replay_scope
from .telemetry import SpanRecord, TelemetryEmitter, TraceContext

__all__ = [
    "EventBus",
    "SpanRecord",
    "StreamingDeltaBatcher",
    "TelemetryEmitter",
    "TraceContext",
    "is_replaying",
    "replay_scope",
]
