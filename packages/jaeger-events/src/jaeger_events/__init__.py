"""jaeger-events: replay-safe EventBus, FencedEventStream, live seam, delta batcher, and OTel telemetry."""

from . import live
from .batcher import StreamingDeltaBatcher
from .bus import (
    EventBus,
    FencedEventStream,
    HandlerCycleError,
    StaleWriterError,
    is_replaying,
    replay_scope,
)
from .telemetry import (
    SpanRecord,
    TelemetryEmitter,
    TraceContext,
    agent_span,
    mark,
    span,
    tool_span,
)

__all__ = [
    "EventBus",
    "FencedEventStream",
    "HandlerCycleError",
    "SpanRecord",
    "StaleWriterError",
    "StreamingDeltaBatcher",
    "TelemetryEmitter",
    "TraceContext",
    "agent_span",
    "is_replaying",
    "live",
    "mark",
    "replay_scope",
    "span",
    "tool_span",
]
