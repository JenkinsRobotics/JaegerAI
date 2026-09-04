"""External agent runtimes exposed as permission-scoped Jaeger delegates."""

from .builtins import register_builtin_delegates
from .contracts import (
    DelegateArtifact,
    DelegateEvent,
    DelegateHandle,
    DelegateRequest,
    DelegateResult,
    DelegateRuntime,
    RuntimeStatus,
)
from .executor import (
    AllDelegatesFailed,
    EnsembleOutcome,
    DelegateExecutionError,
    DelegateExecutor,
    FailoverAttempt,
)
from .registry import DelegateRegistry, get_delegate_registry

__all__ = [
    "AllDelegatesFailed",
    "DelegateArtifact",
    "DelegateEvent",
    "DelegateExecutionError",
    "DelegateExecutor",
    "DelegateHandle",
    "DelegateRegistry",
    "DelegateRequest",
    "DelegateResult",
    "DelegateRuntime",
    "EnsembleOutcome",
    "FailoverAttempt",
    "RuntimeStatus",
    "get_delegate_registry",
    "register_builtin_delegates",
]
