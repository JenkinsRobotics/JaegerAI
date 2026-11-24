"""jaeger-reliability: error classification, credential rotation, zero-event retries, repair, watchdog."""

from .engine import (
    CredentialPool,
    FailoverReason,
    ReliabilityEngine,
    classify_error,
    repair_arguments,
    repair_json_string,
    retry_stream_zero_event_safe,
)

__all__ = [
    "CredentialPool",
    "FailoverReason",
    "ReliabilityEngine",
    "classify_error",
    "repair_arguments",
    "repair_json_string",
    "retry_stream_zero_event_safe",
]
