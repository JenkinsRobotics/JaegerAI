"""AgentRegistry package — Jaeger native + third-party agent catalog."""

from jaeger_ai.core.agent_registry.handoff import (
    HandoffRecord,
    HandoffStub,
    get_handoff_stub,
)
from jaeger_ai.core.agent_registry.registry import (
    AgentRegistry,
    create_agent,
    default_registry_path,
    get_default_registry,
    list_agents,
)
from jaeger_ai.core.agent_registry.specialists import (
    LEAD_AGENT_ID,
    STANDING_SPECIALISTS,
    ensure_standing_specialists,
    specialist_ids,
)
from jaeger_ai.core.agent_registry.types import (
    BUILTIN_THIRD_PARTY,
    AgentKind,
    AgentRecord,
    AgentRole,
    JaegerNativeAgent,
    ThirdPartyAgent,
    is_native,
    is_third_party,
)

__all__ = [
    "AgentKind",
    "AgentRecord",
    "AgentRole",
    "AgentRegistry",
    "BUILTIN_THIRD_PARTY",
    "HandoffRecord",
    "HandoffStub",
    "JaegerNativeAgent",
    "LEAD_AGENT_ID",
    "STANDING_SPECIALISTS",
    "ThirdPartyAgent",
    "create_agent",
    "default_registry_path",
    "ensure_standing_specialists",
    "get_default_registry",
    "get_handoff_stub",
    "is_native",
    "is_third_party",
    "list_agents",
    "specialist_ids",
]
