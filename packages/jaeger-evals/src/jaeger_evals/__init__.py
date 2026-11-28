"""jaeger-evals: SpanTree agentic trajectory evaluators and compaction verifier."""

from .evaluators import CompactionVerification, SpanTree, TraceSpan, verify_compaction_integrity

__all__ = ["CompactionVerification", "SpanTree", "TraceSpan", "verify_compaction_integrity"]
