"""JaegerAI AgentRuntime extensions used by the multimodal engine."""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_agent import JaegerAgent, Message, ProviderAdapter
from jaeger_agent.loop.runtime_bridge import drive_one_turn
from jaeger_ai.core.agent_observability import artifact_paths, safe_preview
from jaeger_ai.core.mind_runtime import JaegerAIRuntime, _PipelineEventAdapter


def _runtime() -> JaegerAIRuntime:
    runtime = JaegerAIRuntime.__new__(JaegerAIRuntime)
    runtime.client = SimpleNamespace()
    runtime._confirmation = None
    runtime._vision_handler = None
    runtime._closed = False
    return runtime


def test_multimodal_turn_preserves_provider_content(monkeypatch) -> None:
    import jaeger_ai.main as app

    received = {}
    adapter = SimpleNamespace(_llama=SimpleNamespace(), llama_kwargs={})
    agent = SimpleNamespace(primary_adapter=adapter)
    ensured = []

    def ensure(*args, **kwargs):
        ensured.append((args, kwargs))
        return agent

    monkeypatch.setattr(app, "_ensure_session_agent", ensure)

    def run_for_voice(
        client,
        text,
        session_key=None,
        *,
        content=None,
        system_prompt_addon="",
    ):
        received.update(
            text=text,
            session=session_key,
            content=content,
            system=system_prompt_addon,
        )
        return {"text": "seen", "error": None}

    monkeypatch.setattr(app, "run_for_voice", run_for_voice)
    runtime = _runtime()
    handler = object()
    runtime.configure_vision(handler)
    content = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        {"type": "text", "text": "inspect"},
    ]

    result = runtime.run_multimodal_turn(
        content,
        text="inspect",
        system_prompt="engine transport prompt",
        session_key="multimodal",
    )

    assert result["text"] == "seen"
    assert received == {
        "text": "inspect",
        "session": "multimodal",
        "content": content,
        "system": "engine transport prompt",
    }
    assert adapter._llama.chat_handler is handler
    assert adapter.llama_kwargs["chat_handler"] is handler
    assert ensured[0][1] == {"scope_tools": True}
    assert agent.skip_final_tools == frozenset()


def test_multimodal_warmup_uses_exact_scoped_agent_prefix(monkeypatch) -> None:
    import jaeger_ai.main as app

    calls = []

    class Adapter:
        llama_kwargs = {}
        _llama = None

        def warmup(self, **kwargs):
            calls.append(("warm", kwargs))
            return True

    agent = SimpleNamespace(
        primary_adapter=Adapter(),
        system_prompt="Jaeger persona",
        tools=["core-tool"],
        skip_final_tools=frozenset({"calculate"}),
    )

    def ensure(client, session_key, **kwargs):
        calls.append(("ensure", session_key, kwargs))
        return agent

    monkeypatch.setattr(app, "_ensure_session_agent", ensure)
    monkeypatch.setitem(app._pipeline, "llm_lock", None)
    runtime = _runtime()

    assert runtime.warmup(
        session_key="multimodal",
        system_prompt="route outputs dynamically",
    )
    assert calls[0] == ("ensure", "multimodal", {"scope_tools": True})
    assert calls[1][0] == "warm"
    assert "Jaeger persona" in calls[1][1]["system_prompt"]
    assert "route outputs dynamically" in calls[1][1]["system_prompt"]
    assert calls[1][1]["tools"] == ["core-tool"]
    assert agent.skip_final_tools == frozenset()


def test_vision_projector_is_seeded_before_lazy_llama_load() -> None:
    runtime = _runtime()
    projector = object()
    adapter = SimpleNamespace(_llama=None, llama_kwargs={})
    runtime._vision_handler = projector
    runtime._apply_vision_handler(SimpleNamespace(primary_adapter=adapter))
    assert adapter.llama_kwargs["chat_handler"] is projector


def test_vision_projector_detaches_from_shared_llama() -> None:
    runtime = _runtime()
    projector = object()
    adapter = SimpleNamespace(
        _llama=SimpleNamespace(chat_handler=projector),
        llama_kwargs={"chat_handler": projector},
    )
    runtime._chatbot_sessions = {
        "multimodal": SimpleNamespace(primary_adapter=adapter),
    }

    runtime.configure_vision(None)

    assert adapter._llama.chat_handler is None
    assert "chat_handler" not in adapter.llama_kwargs


def test_chatbot_lane_builds_an_isolated_zero_tool_agent(monkeypatch) -> None:
    import jaeger_ai.main as app
    import jaeger_agent.loop.runtime_bridge as bridge

    calls = []
    adapter = SimpleNamespace()
    agent = SimpleNamespace(primary_adapter=adapter)

    def build(client, **kwargs):
        calls.append(("build", client, kwargs))
        return agent

    def drive(candidate, text, *, content=None):
        calls.append(("drive", candidate, text, content))
        return {"answer": "chat response"}

    monkeypatch.setattr(bridge, "build_jaeger_agent", build)
    monkeypatch.setattr(bridge, "drive_one_turn", drive)
    monkeypatch.setitem(app._pipeline, "llm_lock", None)
    runtime = _runtime()
    content = [{"type": "text", "text": "hello"}]

    first = runtime.run_chatbot_multimodal_turn(
        content,
        text="hello",
        system_prompt="be brief",
        session_key="multimodal",
    )
    second = runtime.run_chatbot_turn("again", session_key="multimodal")

    assert first == {"text": "chat response", "error": None}
    assert second == {"text": "chat response", "error": None}
    builds = [call for call in calls if call[0] == "build"]
    assert len(builds) == 1
    assert builds[0][2]["tools_enabled"] is False
    assert builds[0][2]["system_prompt"] == "be brief"
    runtime.clear_chatbot_session("multimodal")
    assert runtime._chatbot_sessions == {}


def test_multimodal_clear_evicts_only_its_session(monkeypatch) -> None:
    import jaeger_ai.main as app

    evicted = []
    monkeypatch.setattr(app, "evict_session", evicted.append)
    runtime = _runtime()
    runtime.clear_session("multimodal:2")
    assert evicted == ["multimodal:2"]


def test_runtime_bridge_keeps_image_blocks_in_the_agent_transcript() -> None:
    class Adapter(ProviderAdapter):
        name = "capture"

        def format_messages(self, messages, tools, system):
            return list(messages)

        def call(self, formatted, interrupt_event, **kwargs):
            return Message(role="assistant", content="seen")

        def parse_response(self, raw):
            return raw

        def supports(self, feature: str) -> bool:
            return feature == "vision"

    content = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        {"type": "text", "text": "inspect"},
    ]
    agent = JaegerAgent(adapter=Adapter())
    result = drive_one_turn(agent, "inspect", content=content)
    assert result["answer"] == "seen"
    assert agent.messages[0]["content"] == content


def test_multimodal_prompt_adds_transport_rules_without_replacing_persona() -> None:
    from jaeger_ai.main import _apply_multimodal_system_prompt

    agent = SimpleNamespace(system_prompt="You are Jaeger, concise and curious.")
    _apply_multimodal_system_prompt(agent, "[context:] carries acoustic evidence.")
    assert agent.system_prompt.startswith("You are Jaeger, concise and curious.")
    assert agent.system_prompt.endswith("[context:] carries acoustic evidence.")
    _apply_multimodal_system_prompt(agent, "new session-specific instruction")
    assert agent.system_prompt.count("# Multimodal transport") == 1
    assert "new session-specific instruction" in agent.system_prompt


def test_observable_tool_output_is_redacted_bounded_and_finds_artifacts() -> None:
    value = {
        "path": "/tmp/report.md",
        "nested": {"output_file": "/tmp/chart.png"},
        "api_key": "should-not-be-visible",
        "body": "x" * 2_000,
    }
    preview = safe_preview(value, limit=160)
    assert len(preview) <= 160
    assert "should-not-be-visible" not in preview
    assert artifact_paths(value) == ("/tmp/report.md", "/tmp/chart.png")


def test_pipeline_event_adapter_tags_workspace_output_with_session() -> None:
    class Events:
        def __init__(self) -> None:
            self.tools = []
            self.activities = []

        def tool(self, name, phase, **payload):
            self.tools.append((name, phase, payload))

        def activity(self, kind, text, **payload):
            self.activities.append((kind, text, payload))

    events = Events()
    adapter = _PipelineEventAdapter(events)
    adapter.publish(
        "tool.output",
        name="write_file",
        ok=True,
        elapsed_s=0.5,
        detail="saved",
        artifacts=("/tmp/report.md",),
        session="multimodal",
    )
    assert events.tools == [
        (
            "write_file",
            "output",
            {"elapsed_s": 0.5, "detail": "saved", "session": "multimodal"},
        )
    ]
    assert events.activities == [
        ("artifact", "/tmp/report.md", {"session": "multimodal"})
    ]
