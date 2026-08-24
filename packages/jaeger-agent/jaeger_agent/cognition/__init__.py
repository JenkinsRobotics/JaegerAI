"""Durable SI work-state: commitments, runs, checkpoints, effects.

The layering, outermost first:

    commitment   what the SI intends            survives everything
    run          one attempt at it              survives the process
    checkpoint   how far that attempt got       survives the crash
    effect       what it did to the world       happens at most once

All four are rows written by deterministic code in
``jaeger_agent.cognition.lifecycle``. A model proposes; this package
decides.
"""

from jaeger_agent.cognition.commitments import (
    STATES,
    Commitment,
    CommitmentError,
    CommitmentStore,
    InMemoryCommitmentStore,
)
from jaeger_agent.cognition.effects import (
    Effect,
    EffectError,
    EffectIndeterminate,
    EffectLedger,
    InMemoryEffectLedger,
)
from jaeger_agent.cognition.lifecycle import (
    ALLOWED,
    RESUMABLE,
    TERMINAL,
    LifecycleError,
    check_transition,
)
from jaeger_agent.cognition.runs import (
    Checkpoint,
    InMemoryRunStore,
    Run,
    RunError,
    RunStore,
    pid_is_alive,
)

__all__ = [
    "ALLOWED",
    "RESUMABLE",
    "STATES",
    "TERMINAL",
    "Checkpoint",
    "Commitment",
    "CommitmentError",
    "CommitmentStore",
    "Effect",
    "EffectError",
    "EffectIndeterminate",
    "EffectLedger",
    "InMemoryCommitmentStore",
    "InMemoryEffectLedger",
    "InMemoryRunStore",
    "LifecycleError",
    "Run",
    "RunError",
    "RunStore",
    "check_transition",
    "pid_is_alive",
]
