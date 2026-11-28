"""jaeger-gateway: standalone single-fiber Gateway server, runtime, zombie-fenced SSE, WAL store & auth."""

from .auth import AuthDecision, GatewayAuthPolicy
from .authorized_tasks import (
    AuthorizedGrantStore,
    AuthorizedSettings,
    AuthorizedTaskEngine,
    FolderGrant,
    TaskAttemptReceipt,
    looks_like_provider_refusal,
)
from .client import JaegerClient, JaegerClientError
from .coordinator import RunCoordinator, RunExecutor
from .runtime import ModularGatewayRuntime, serve_modular_gateway
from .server import ACTOR_KEY, create_gateway_app
from .store import GatewayStore, RequestConflictError
from .stream import SessionEventHub, StaleWriterError, format_sse

__all__ = [
    "ACTOR_KEY",
    "AuthDecision",
    "AuthorizedGrantStore",
    "AuthorizedSettings",
    "AuthorizedTaskEngine",
    "FolderGrant",
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
    "TaskAttemptReceipt",
    "create_gateway_app",
    "format_sse",
    "looks_like_provider_refusal",
    "serve_modular_gateway",
]
