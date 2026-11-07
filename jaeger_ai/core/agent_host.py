"""Product-owned adapters injected into the reusable agent package.

Factories remain lazy to preserve startup order. Authority and tool repair still
run in their existing canonical modules; the agent never imports its host.
"""
from importlib import import_module


def bind_agent_host() -> None:
    from jaeger_agent.core.host import bind_services

    modules = {
        "authority": "jaeger_ai.core.entity.authority",
        "entity_events": "jaeger_ai.core.entity.events",
        "entity_runtime": "jaeger_ai.core.entity.runtime",
        "tool_repair": "jaeger_ai.core.runtime.tool_repair",
        "instance_schemas": "jaeger_ai.core.instance.schemas",
        "cli_backends": "jaeger_ai.features.cli_backends.discovery",
        "agent_registry": "jaeger_ai.core.agent_registry",
        "skill_guard": "jaeger_ai.core.safety.skills_guard",
        "pipeline": "jaeger_ai.main",
        "containers": "jaeger_ai.core.runtime.container_service",
        "shared_memory": "jaeger_ai.features.shared_memory.honcho_client",
    }
    bind_services({name: lambda module=module: import_module(module)
                   for name, module in modules.items()})
