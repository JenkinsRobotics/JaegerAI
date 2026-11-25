"""jaeger-gateway: standalone single-fiber Gateway coordinator, zombie-fenced SSE, WAL store & auth."""

from .auth import AuthDecision, GatewayAuthPolicy
from .coordinator import RunCoordinator, RunExecutor
from .store import GatewayStore, RequestConflictError
from .stream import SessionEventHub, StaleWriterError, format_sse

__all__ = [
    "AuthDecision",
    "GatewayAuthPolicy",
    "GatewayStore",
    "RequestConflictError",
    "RunCoordinator",
    "RunExecutor",
    "SessionEventHub",
    "StaleWriterError",
    "format_sse",
]
