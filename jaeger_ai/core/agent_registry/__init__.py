"""AgentRegistry package — Jaeger native + third-party agent catalog."""

from jaeger_ai.core.agent_registry.registry import (
    AgentRegistry,
    create_agent,
    default_registry_path,
    get_default_registry,
    list_agents,
)
from jaeger_ai.core.agent_registry.types import (
    BUILTIN_THIRD_PARTY,
    AgentKind,
    AgentRecord,
    JaegerNativeAgent,
    ThirdPartyAgent,
    is_native,
    is_third_party,
)

__all__ = [
    "AgentKind",
    "AgentRecord",
    "AgentRegistry",
    "BUILTIN_THIRD_PARTY",
    "JaegerNativeAgent",
    "ThirdPartyAgent",
    "create_agent",
    "default_registry_path",
    "get_default_registry",
    "is_native",
    "is_third_party",
    "list_agents",
]
