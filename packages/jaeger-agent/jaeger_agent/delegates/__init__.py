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
from .executor import DelegateExecutionError, DelegateExecutor
from .registry import DelegateRegistry, get_delegate_registry

__all__ = [
    "DelegateArtifact",
    "DelegateEvent",
    "DelegateExecutionError",
    "DelegateExecutor",
    "DelegateHandle",
    "DelegateRegistry",
    "DelegateRequest",
    "DelegateResult",
    "DelegateRuntime",
    "RuntimeStatus",
    "get_delegate_registry",
    "register_builtin_delegates",
]
