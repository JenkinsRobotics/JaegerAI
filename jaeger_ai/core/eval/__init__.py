"""External Agent Evaluation Suite package (Workstream 17)."""
from __future__ import annotations

from .harness import ExternalEvalHarness
from .schemas import (
    EvaluationReport,
    EvaluationTask,
    EvaluationVerdict,
    FailureCategory,
)
from .suites import get_standard_eval_suite

__all__ = [
    "ExternalEvalHarness",
    "EvaluationReport",
    "EvaluationTask",
    "EvaluationVerdict",
    "FailureCategory",
    "get_standard_eval_suite",
]
