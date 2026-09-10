"""Jaeger Dispatcher feature package.

Provides task coordination, focus work persistence, and session routing between
the operator conversation and autonomous background workers.
"""

from .store import DispatcherStore, DISPATCHER, FOCUS_PREFIX, FOCUS_CONTEXT, TOOLSETS, task_kind
from .router import PRIMARY_SESSIONS, is_primary_session, normalize_session_key, prepare_turn_text
from .sidecar import EXTENSION_ID, Handler as SidecarHandler, run_server as run_sidecar

__all__ = [
    "DispatcherStore",
    "DISPATCHER",
    "FOCUS_PREFIX",
    "FOCUS_CONTEXT",
    "TOOLSETS",
    "task_kind",
    "PRIMARY_SESSIONS",
    "is_primary_session",
    "normalize_session_key",
    "prepare_turn_text",
    "EXTENSION_ID",
    "SidecarHandler",
    "run_sidecar",
]
