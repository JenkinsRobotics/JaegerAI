"""Privacy and sensitivity governance gate shim.

For full routing and gating logic, see :mod:`jaeger_ai.core.models.router`.
"""

from __future__ import annotations

from jaeger_ai.core.models.router import (
    SensitivityDecision,
    apply_sensitivity_routing,
    classify,
    decide,
    estimate_tokens,
    log_decision,
)

__all__ = [
    "SensitivityDecision",
    "apply_sensitivity_routing",
    "classify",
    "decide",
    "estimate_tokens",
    "log_decision",
]
