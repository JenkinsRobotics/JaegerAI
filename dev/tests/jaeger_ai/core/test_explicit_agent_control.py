"""Control-plane invariants: natural language never grants authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jaeger_ai.core.gateway import session_hygiene
from jaeger_ai.core.instance.schemas import PersonaConfig
from jaeger_ai.core.runtime.autonomous_runner import should_run_autonomous


def test_durable_loop_requires_explicit_goal_or_host_state():
    assert not should_run_autonomous("process these 300 notes until done")
    assert not should_run_autonomous("fix the repository and run tests")
    assert should_run_autonomous("/goal process these 300 notes")


def test_persona_configuration_has_no_second_agent_mode():
    config = PersonaConfig()
    assert "mode" not in config.model_dump()


def test_session_lifecycle_uses_explicit_kind_not_names():
    named_like_probe = {
        "session_id": "sota-test-chat",
        "title": "Benchmark acceptance test",
        "message_count": 0,
        "metadata": {},
    }
    explicit_probe = {
        **named_like_probe,
        "session_id": "ordinary-id",
        "title": "Ordinary title",
        "metadata": {"session_kind": "probe"},
    }
    assert session_hygiene.classify(named_like_probe)[0] == "chat"
    assert session_hygiene.classify(explicit_probe)[0] == "junk"


def test_gateway_execution_does_not_call_auto_specialist_router():
    # Structural pin: the method may remain temporarily for migration callers,
    # but the live turn owner must not invoke it.
    import inspect
    from jaeger_ai.core.gateway.server import JaegerGatewayApp

    source = inspect.getsource(JaegerGatewayApp._execute_turn_inner)
    assert "self._auto_route(" not in source


def test_agent_turn_does_not_infer_toolsets_or_auto_inject_skills():
    import inspect
    from jaeger_agent.loop.jaeger_agent import JaegerAgent

    source = inspect.getsource(JaegerAgent.run_turn)
    assert "infer_toolsets" not in source
    assert "_auto_route_skill" not in source


def test_agent_policy_prefers_semantic_browser_for_websites():
    prompt = (
        Path(__file__).resolve().parents[4]
        / "packages/jaeger-agent/jaeger_agent/prompts/agent_system_prompt.md"
    ).read_text()
    assert "Websites — semantic browser first" in prompt
    assert "use the DOM-aware `browser` tool" in prompt
    assert "Use `computer_use` for native applications" in prompt
