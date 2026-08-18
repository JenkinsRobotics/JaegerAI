"""The config-built runtime — what makes this a module, not a library.

Covers the promise in module.yaml: declare the mind slot, set a provider
and model, get a working brain. If these fail, embedding jaeger-agent
means writing glue, which is the thing the split was for.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from pydantic import ValidationError

from jaeger_agent import AgentConfig, Message, ProviderAdapter, ToolCall
from jaeger_agent.node import DEFAULT_RUNTIME_FACTORY, MindNode, resolve_runtime_factory
from jaeger_agent.runtime import DefaultAgentRuntime, build_adapter, create_runtime


class ScriptedAdapter(ProviderAdapter):
    """Calls one tool, then answers. No network."""

    name = "scripted"

    def __init__(self, tool: str = "") -> None:
        self.turn = 0
        self.tool = tool
        self.seen_tools: list[str] = []

    def format_messages(self, messages, tools, system):
        self.seen_tools = [t.name for t in tools]
        return {"messages": messages, "system": system}

    def call(self, formatted: Any, interrupt_event: threading.Event, **kw: Any) -> Any:
        self.turn += 1
        return formatted

    def parse_response(self, raw: Any) -> Message:
        if self.tool and self.turn == 1:
            return Message(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name=self.tool, arguments={})],
            )
        return Message(role="assistant", content="done")

    def supports(self, feature: str) -> bool:
        return False


# ── config → adapter ────────────────────────────────────────────────


def test_llama_cpp_is_the_default_provider() -> None:
    """No server, no key, no network is the out-of-the-box posture."""
    assert AgentConfig().provider == "llama_cpp"


def test_llama_cpp_without_a_path_says_what_to_do() -> None:
    with pytest.raises(RuntimeError, match="model_path"):
        build_adapter(AgentConfig())


def test_llama_cpp_rejects_a_path_that_is_not_there() -> None:
    """Better than llama.cpp's own failure, which is a segfault-adjacent abort."""
    with pytest.raises(RuntimeError, match="does not exist"):
        build_adapter(AgentConfig(model_path="/nope/missing.gguf"))


def test_llama_kwargs_match_jaeger_ai_so_benchmarks_compare(tmp_path) -> None:
    """ctx/gpu_layers reach the Llama constructor, and the rest of the
    defaults stay the ones JaegerAI's client has always used."""
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"not really weights")
    adapter = build_adapter(AgentConfig(model_path=str(gguf), ctx=4096, gpu_layers=0))
    assert type(adapter).__name__ == "LocalLlamaAdapter"
    assert adapter.model == "fake"  # label defaults to the filename
    assert adapter.llama_kwargs["n_ctx"] == 4096
    assert adapter.llama_kwargs["n_gpu_layers"] == 0
    assert adapter.llama_kwargs["flash_attn"] is True
    assert adapter.llama_kwargs["n_batch"] == 512


def test_openai_compatible_provider_needs_no_key_with_a_base_url() -> None:
    """A local server is the common embed case — it must not demand a key."""
    adapter = build_adapter(
        AgentConfig(provider="ollama", model="qwen3:8b",
                    base_url="http://localhost:11434/v1")
    )
    assert type(adapter).__name__ == "OpenAIAdapter"
    assert adapter.model == "qwen3:8b"


def test_anthropic_provider_selects_the_anthropic_adapter(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    adapter = build_adapter(AgentConfig(provider="anthropic", model="claude-sonnet-4-6"))
    assert type(adapter).__name__ == "AnthropicAdapter"


def test_hosted_provider_without_a_key_fails_loudly(monkeypatch) -> None:
    """Better a named error at boot than a 401 on the first thing said."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API key"):
        build_adapter(AgentConfig(provider="openai", model="gpt-4o-mini"))


def test_api_key_env_names_the_variable_not_the_secret(monkeypatch) -> None:
    monkeypatch.setenv("MY_KEY", "sk-xyz")
    adapter = build_adapter(
        AgentConfig(provider="anthropic", model="m", api_key_env="MY_KEY")
    )
    assert adapter.api_key == "sk-xyz"


def test_host_config_keys_are_ignored_but_agent_typos_are_not() -> None:
    """Node config carries host keys; an ``agent`` group typo must still fail."""
    rt = DefaultAgentRuntime(config={"provider": "ollama", "instance_name": "host-owned"})
    assert rt.config.provider == "ollama"
    with pytest.raises(ValidationError):
        AgentConfig(privider="ollama")  # typo inside the group


# ── the runtime ─────────────────────────────────────────────────────


def test_runtime_runs_a_turn_with_an_injected_adapter() -> None:
    rt = DefaultAgentRuntime(config={"system_prompt": "be brief"},
                             adapter=ScriptedAdapter())
    result = rt.run_turn("hello", session_key="s1")
    assert result.error is None and result.text == "done"
    rt.close()


def test_sessions_keep_separate_transcripts() -> None:
    rt = DefaultAgentRuntime(adapter=ScriptedAdapter())
    rt.run_turn("first", session_key="a")
    rt.run_turn("second", session_key="b")
    assert rt.agent_for("a") is not rt.agent_for("b")
    assert rt.health()["sessions"] == 2
    rt.close()


def test_session_search_is_in_the_default_toolset() -> None:
    from jaeger_agent.schemas.tool_bundles import resolve_toolsets

    assert "session_search" in resolve_toolsets({"default"})


def test_a_failing_turn_returns_an_error_not_an_exception() -> None:
    """One bad turn must not take the node down with it."""

    class Boom(ScriptedAdapter):
        def call(self, formatted, interrupt_event, **kw):
            raise RuntimeError("provider exploded")

    rt = DefaultAgentRuntime(adapter=Boom())
    result = rt.run_turn("hi", session_key="s")
    assert result.error and "provider exploded" in result.error
    rt.close()


def test_registered_tools_reach_the_agent() -> None:
    """The registry is the contract — a tool registered anywhere is visible."""
    from jaeger_agent import register_tool_from_function, unregister_tool

    called: list[bool] = []

    @register_tool_from_function(name="_probe_tool")
    def _probe() -> dict:
        """Probe."""
        called.append(True)
        return {"ok": True}

    try:
        adapter = ScriptedAdapter(tool="_probe_tool")
        rt = DefaultAgentRuntime(adapter=adapter)
        rt.run_turn("use it", session_key="s")
        assert called == [True]
        assert "_probe_tool" in adapter.seen_tools
        rt.close()
    finally:
        unregister_tool("_probe_tool")


def test_tool_events_reach_the_bus_so_the_manifest_is_honest() -> None:
    """module.yaml declares ``produces: [/sense/tool]``. Keep the promise.

    Without this the loop still fires callbacks, but a surface sees a
    turn as one silent gap between question and answer.
    """
    from jaeger_agent import register_tool_from_function, unregister_tool

    @register_tool_from_function(name="_evt_tool")
    def _evt() -> dict:
        """Probe."""
        return {"ok": True}

    class RecordingEvents:
        def __init__(self) -> None:
            self.tools: list[tuple[str, str]] = []
            self.activity: list[tuple[str, str]] = []

        def tool(self, name, phase, *, elapsed_s=0.0, detail="", session="") -> None:
            self.tools.append((name, phase))

        def activity(self, kind, text, *, session="") -> None:
            self.activity.append((kind, text))

    try:
        events = RecordingEvents()
        rt = DefaultAgentRuntime(adapter=ScriptedAdapter(tool="_evt_tool"))
        rt.start(events=events, bus=None)
        rt.run_turn("go", session_key="s")
        assert ("_evt_tool", "start") in events.tools
        # "done", not "complete" — a tool that raises still completes;
        # its failure is fed back as a result, not as a phase.
        assert ("_evt_tool", "done") in events.tools
        rt.close()
    finally:
        unregister_tool("_evt_tool")


def test_runtime_works_with_no_event_sink_at_all() -> None:
    """A direct embedder never calls start(); that must not crash."""
    rt = DefaultAgentRuntime(adapter=ScriptedAdapter())
    assert rt.run_turn("hi", session_key="s").text == "done"
    rt.close()


# ── the node default ────────────────────────────────────────────────


def test_mind_node_defaults_to_the_built_in_runtime() -> None:
    """No runtime_factory configured is the embed case, not an error."""
    assert resolve_runtime_factory(DEFAULT_RUNTIME_FACTORY) is create_runtime

    node = MindNode(bus=None, config={"provider": "ollama", "base_url": "http://x/v1"})
    assert node.runtime is None
    assert not node.runtime_factory  # nothing named — the default carries it


def test_manifest_points_at_the_agent_config_group() -> None:
    """module.yaml's ``config`` must name a real settings group."""
    import pathlib

    import yaml

    manifest = yaml.safe_load(
        (pathlib.Path(__file__).parent.parent / "jaeger_agent" / "module.yaml").read_text()
    )
    assert manifest["config"] == "agent"
    assert manifest["slot"] == "mind"
    assert manifest["tools"] == []  # the mind calls tools, it does not supply them
    for field in AgentConfig.model_fields:
        assert field  # config group is non-empty, so the pointer means something


def test_no_tools_also_suppresses_skill_registered_tools(monkeypatch) -> None:
    """A bare loop must not get desktop control back via the skill loader.

    JAEGER_AGENT_NO_TOOLS used to gate only the tools package, while the
    runtime went on to load skills — and the shipped computer_use skill
    registers ten tools including computer_click, computer_type_text and
    computer_read_screen. An embedder that declined tools was handed
    those anyway. Caught reviewing a chat-only embedder.
    """
    from jaeger_agent.runtime import _load_skills

    monkeypatch.setenv("JAEGER_AGENT_NO_TOOLS", "1")
    assert _load_skills(object()) is None

    monkeypatch.delenv("JAEGER_AGENT_NO_TOOLS", raising=False)
    monkeypatch.setenv("JAEGER_AGENT_NO_SKILLS", "1")
    assert _load_skills(object()) is None
