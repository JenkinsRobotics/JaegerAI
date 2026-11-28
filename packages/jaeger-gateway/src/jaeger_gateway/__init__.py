"""jaeger-gateway: standalone single-fiber Gateway server, runtime, zombie-fenced SSE, WAL store & auth."""

from .auth import AuthDecision, GatewayAuthPolicy
from .client import JaegerClient, JaegerClientError
from .coordinator import RunCoordinator, RunExecutor
from .runtime import ModularGatewayRuntime, serve_modular_gateway
from .server import ACTOR_KEY, create_gateway_app
from .store import GatewayStore, RequestConflictError
from .stream import SessionEventHub, StaleWriterError, format_sse

__all__ = [
    "ACTOR_KEY",
    "AuthDecision",
    "GatewayAuthPolicy",
    "GatewayStore",
    "JaegerClient",
    "JaegerClientError",
    "ModularGatewayRuntime",
    "RequestConflictError",
    "RunCoordinator",
    "RunExecutor",
    "SessionEventHub",
    "StaleWriterError",
    "create_gateway_app",
    "format_sse",
    "serve_modular_gateway",
]
