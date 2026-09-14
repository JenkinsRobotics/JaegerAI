"""Behavior contracts for the packaged multimodal framework."""

from __future__ import annotations

import threading
from typing import Any

from pydantic import BaseModel

from jaeger_agent import JaegerAgent, Message, ProviderAdapter, ToolDef
from jaeger_agent.core import context
from jaeger_agent.core import engine as engine_module
from jaeger_agent.core.context import context_line
from jaeger_agent.core.engine import AgentRuntimeBrain, GemmaMultimodal
from jaeger_agent.core.runtime import DefaultAgentRuntime


class RecordingRuntime:
    def __init__(self) -> None:
        self.turns: list[tuple[Any, str]] = []
        self.cleared: list[str] = []

    def run_turn(self, text: str, *, session_key: str) -> str:
        self.turns.append((text, session_key))
        return "answer"

    def close(self) -> None:
        return None


def test_context_line_carries_speaker_pitch_holding_and_wake() -> None:
    line = context_line(
        [
            {
                "speaker": 2,
                "speaker_conf": 0.81,
                "holding": True,
                "wake": "hey jaeger",
                "prosody": {"pitch_hz": 204.0, "energy_db": -18.0},
            }
        ],
        "turn",
    )
    for part in (
        "speaker=S2",
        "conf=81%",
        "pitch_hz=204.0",
        "holding=yes",
        "wake=hey jaeger",
    ):
        assert part in line


def test_runtime_brain_warms_after_vision_configuration_without_fake_memory() -> None:
    class LifecycleRuntime(RecordingRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.handler = None
            self.warmed = None

        def configure_vision(self, handler) -> None:
            self.handler = handler

        def warmup(self, *, session_key: str, system_prompt: str) -> None:
            self.warmed = (session_key, system_prompt)

    runtime = LifecycleRuntime()
    brain = AgentRuntimeBrain(runtime, "voice")
    handler = object()

    brain.load(handler, lambda _message: None, system_prompt="system")

    assert runtime.handler is handler
    assert runtime.warmed == ("voice", "system")
    assert runtime.turns == []


def test_runner_no_agentic_tools_selects_runtime_chatbot_mode(monkeypatch) -> None:
    from jaeger_agent.core import runner

    seen = {}
    engine = object()

    def build_engine(**kwargs):
        seen.update(kwargs)
        return engine

    monkeypatch.setattr(runner, "GemmaMultimodal", build_engine)
    monkeypatch.setattr(runner, "run_mic", lambda candidate: int(candidate is not engine))

    assert runner.main(["--no-agentic-tools", "--audio", "plain"]) == 0
    assert seen["runtime_config"] == {"tools_enabled": False}
    assert seen["use_offline_fallback"] is False
    assert seen["config"].output_mode == "speech"


def test_runner_agentic_mode_defaults_to_dynamic_output(monkeypatch) -> None:
    from jaeger_agent.core import runner

    seen = {}
    engine = object()

    monkeypatch.setattr(
        runner,
        "GemmaMultimodal",
        lambda **kwargs: seen.update(kwargs) or engine,
    )
    monkeypatch.setattr(runner, "run_mic", lambda candidate: int(candidate is not engine))

    assert runner.main(["--audio", "plain"]) == 0
    assert seen["config"].output_mode == "dynamic"


def test_runner_explicit_output_mode_wins(monkeypatch) -> None:
    from jaeger_agent.core import runner

    seen = {}
    engine = object()

    monkeypatch.setattr(
        runner,
        "GemmaMultimodal",
        lambda **kwargs: seen.update(kwargs) or engine,
    )
    monkeypatch.setattr(runner, "run_mic", lambda candidate: int(candidate is not engine))

    assert runner.main(["--audio", "plain", "--output-mode", "mirror"]) == 0
    assert seen["config"].output_mode == "mirror"


def test_vision_projector_closes_native_context_once() -> None:
    class ExitStack:
        def __init__(self) -> None:
            self.calls = 0

        def close(self) -> None:
            self.calls += 1

    class Handler:
        def __init__(self) -> None:
            self._exit_stack = ExitStack()

    node = engine_module.vis_mod.build()
    handler = Handler()
    node.handler = handler
    node.ready = True

    node.close()
    node.close()

    assert handler._exit_stack.calls == 1
    assert node.handler is None
    assert node.ready is False


def test_engine_closes_vision_before_language_model() -> None:
    engine = GemmaMultimodal(play=False, runtime=RecordingRuntime())
    order = []
    engine.node_vision.close = lambda: order.append("vision")
    engine.node_llm.close = lambda: order.append("llm")

    engine.close()

    assert order == ["vision", "llm"]


def test_structured_context_reaches_plain_agent_runtime_without_second_memory() -> None:
    runtime = RecordingRuntime()
    engine = GemmaMultimodal(play=False, runtime=runtime, audio_mode="structured")
    engine._speak = lambda _text: None
    prior = context.STRUCTURED_CONTEXT
    context.STRUCTURED_CONTEXT = True
    try:
        engine._respond("remember this", turns=[{"speaker": 2, "speaker_conf": 0.8}])
    finally:
        context.STRUCTURED_CONTEXT = prior

    submitted, _session = runtime.turns[0]
    assert submitted.startswith("[input: speech]\n[context: speaker=S2")
    assert submitted.endswith("\nremember this")
    assert engine._history == []


def test_dynamic_output_keeps_an_ordinary_answer_text_only() -> None:
    events = []
    engine = GemmaMultimodal(
        play=False,
        runtime=RecordingRuntime(),
        audio_mode="plain",
        output_mode="dynamic",
        on_event=events.append,
    )
    spoken = []
    engine._speak = spoken.append

    engine.send_text("answer in the window")

    assistant = next(event for event in events if event.kind == "assistant")
    assert assistant.text == "answer"
    assert assistant.data == {
        "display": True,
        "channels": ("text",),
        "source": "model-text-fallback",
    }
    assert spoken == []


def test_dynamic_typed_output_selects_engine_owned_speech() -> None:
    class SpeakingRuntime(RecordingRuntime):
        def run_turn(self, text: str, *, session_key: str) -> str:
            self.turns.append((text, session_key))
            return "[OUTPUT:SPEECH] Here is the spoken answer."

    events = []
    engine = GemmaMultimodal(
        play=False,
        runtime=SpeakingRuntime(),
        audio_mode="plain",
        output_mode="dynamic",
        on_event=events.append,
    )
    spoken = []
    engine._speak = spoken.append

    engine.send_text("say it")

    assistant = next(event for event in events if event.kind == "assistant")
    assert assistant.text == ""
    assert assistant.data["channels"] == ("speech",)
    assert assistant.data["source"] == "model-output-directive"
    assert spoken == ["Here is the spoken answer."]


def test_real_agent_loop_cannot_see_tts_tool_and_uses_one_final_response() -> None:
    from jaeger_agent.core.availability import _slot_ready_for_tool

    class SpeechArgs(BaseModel):
        text: str

    class SpeechChoosingAdapter(ProviderAdapter):
        name = "speech-choosing"

        def __init__(self) -> None:
            self.turn = 0
            self.seen_tools: list[str] = []

        def format_messages(self, messages, tools, system):
            self.seen_tools = [tool.name for tool in tools]
            return messages

        def call(self, formatted, interrupt_event: threading.Event, **kwargs):
            self.turn += 1
            return formatted

        def parse_response(self, raw) -> Message:
            return Message(
                role="assistant",
                content="[OUTPUT:SPEECH] Loop-selected speech",
            )

        def supports(self, feature: str) -> bool:
            return False

    adapter = SpeechChoosingAdapter()
    speech_tool = ToolDef(
        name="text_to_speech",
        description="Select speech output.",
        args_model=SpeechArgs,
        fn=lambda text: {"spoken": True, "text": text},
        check_fn=lambda: bool(_slot_ready_for_tool("text_to_speech")),
    )

    class LoopRuntime(RecordingRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.agent = JaegerAgent(adapter=adapter, tools=[speech_tool])

        def run_turn(self, text: str, *, session_key: str) -> str:
            self.turns.append((text, session_key))
            return self.agent.run_turn(text)

    runtime = LoopRuntime()
    events = []
    engine = GemmaMultimodal(
        play=False,
        runtime=runtime,
        audio_mode="plain",
        output_mode="dynamic",
        on_event=events.append,
    )
    spoken = []
    engine._speak = spoken.append

    engine.send_text("choose speech")

    assistant = next(event for event in events if event.kind == "assistant")
    assert "text_to_speech" not in adapter.seen_tools
    assert adapter.turn == 1
    assert assistant.data["channels"] == ("speech",)
    assert spoken == ["Loop-selected speech"]


def test_speech_mode_preserves_the_original_always_tts_pipeline() -> None:
    engine = GemmaMultimodal(
        play=False,
        runtime=RecordingRuntime(),
        audio_mode="plain",
        output_mode="speech",
    )
    spoken = []
    engine._speak = spoken.append

    engine.send_text("legacy benchmark turn")

    assert spoken == ["answer"]


def test_model_can_choose_silence() -> None:
    class SilentRuntime(RecordingRuntime):
        def run_turn(self, text: str, *, session_key: str) -> str:
            self.turns.append((text, session_key))
            return "[SILENT]"

    events = []
    engine = GemmaMultimodal(
        play=False,
        runtime=SilentRuntime(),
        audio_mode="plain",
        output_mode="dynamic",
        on_event=events.append,
    )
    spoken = []
    engine._speak = spoken.append

    engine.send_text("no acknowledgement needed")

    assistant = next(event for event in events if event.kind == "assistant")
    assert assistant.text == ""
    assert assistant.data["channels"] == ()
    assert spoken == []


def test_typed_dismissal_speaks_before_wake_rearms_and_changes_session() -> None:
    runtime = RecordingRuntime()
    events = []
    engine = GemmaMultimodal(
        play=False,
        runtime=runtime,
        audio_mode="plain",
        on_event=events.append,
    )
    spoken = []
    engine._speak = spoken.append
    old_session = engine.node_llm.session_key
    engine._turns = 3
    engine._followup_deadline = 99.0

    engine.send_text("goodbye")

    assert spoken == ["Goodbye."]
    assert engine.node_llm.session_key != old_session
    assert engine._turns == 0
    assert engine._followup_deadline == 0.0
    goodbye_index = next(i for i, event in enumerate(events) if event.kind == "assistant")
    wake_index = next(
        i for i, event in enumerate(events)
        if event.kind == "session" and event.text == "Mode"
    )
    assert goodbye_index < wake_index


def test_image_waits_for_and_rides_the_next_turn() -> None:
    class MultimodalRuntime(RecordingRuntime):
        def run_multimodal_turn(
            self,
            content: Any,
            *,
            text: str,
            system_prompt: str,
            session_key: str,
        ) -> str:
            self.turns.append((content, session_key))
            return "seen"

    runtime = MultimodalRuntime()
    engine = GemmaMultimodal(play=False, runtime=runtime, audio_mode="plain")
    engine._speak = lambda _text: None
    engine.attach_image("data:image/png;base64,AA==")
    engine.send_text("what is this?")

    content, _session = runtime.turns[0]
    assert content[0]["type"] == "image_url"
    assert content[1] == {"type": "text", "text": "[input: text]\nwhat is this?"}
    assert engine._pending_image is None


def test_builtin_runtime_keeps_multimodal_content_in_its_single_transcript() -> None:
    class CapturingAdapter(ProviderAdapter):
        name = "capturing"

        def __init__(self) -> None:
            self.messages = []

        def format_messages(self, messages, tools, system):
            self.messages = list(messages)
            return messages

        def call(self, formatted, interrupt_event: threading.Event, **kwargs):
            return formatted

        def parse_response(self, raw) -> Message:
            return Message(role="assistant", content="seen")

        def supports(self, feature: str) -> bool:
            return feature == "vision"

    adapter = CapturingAdapter()
    runtime = DefaultAgentRuntime(adapter=adapter)
    engine = GemmaMultimodal(play=False, runtime=runtime, audio_mode="plain")
    engine._speak = lambda _text: None
    engine.attach_image("data:image/png;base64,AA==")
    engine.send_text("inspect")

    assert adapter.messages[0]["content"][0]["type"] == "image_url"
    assert len(runtime.agent_for("multimodal").messages) == 2
    assert engine._history == []


def test_optional_offline_fallback_retains_only_eight_exchanges() -> None:
    engine = GemmaMultimodal(
        play=False,
        audio_mode="plain",
        use_offline_fallback=True,
    )

    for index in range(12):
        engine._remember(f"q{index}", f"a{index}")

    assert len(engine._history) == 16
    assert engine.config.output_mode == "speech"
    assert engine._history[0] == {"role": "user", "content": "q4"}
    assert engine._history[-1] == {"role": "assistant", "content": "a11"}


def test_public_session_controls_keep_floor_policy_in_the_engine() -> None:
    runtime = RecordingRuntime()
    engine = GemmaMultimodal(play=False, runtime=runtime, audio_mode="structured")
    states = []
    engine.on_event = lambda event: states.append((event.kind, event.text, event.data))
    assert engine._stt_lock is engine.node_stt._lock

    engine.set_barge_mode("continue")
    assert engine_module.dxr.BARGE_MODE == "continue"
    assert any(row[:2] == ("session", "Barge") and row[2] == "continue" for row in states)

    engine.set_paused(True)
    assert engine._paused.is_set()
    engine.set_paused(False)
    assert not engine._paused.is_set()

    engine.speaking.set()
    engine.force_listen()
    assert engine._force_listen_evt.is_set()
    engine.set_barge_mode("stop")
    assert engine_module.dxr.BARGE_MODE == "stop"


def test_mode_change_during_answer_applies_only_to_next_turn(monkeypatch):
    runtime = RecordingRuntime()
    runtime.agentic_tools = True
    engine = GemmaMultimodal(play=False, runtime=runtime, audio_mode="plain")
    spoken = []
    monkeypatch.setattr(engine, "_speak", spoken.append)

    def first_answer(text, image):
        engine.set_agentic_tools(False)
        assert runtime.agentic_tools is True
        assert engine.config.output_mode == "dynamic"
        return "[OUTPUT:TEXT] current answer"

    monkeypatch.setattr(engine, "_answer", first_answer)
    engine.send_text("first")
    assert not spoken
    monkeypatch.setattr(engine, "_answer", lambda *_: "chatbot answer")
    engine.send_text("second")
    assert runtime.agentic_tools is False
    assert engine.config.output_mode == "speech"
    assert spoken == ["chatbot answer"]


def test_force_listen_cancels_runtime_and_suppresses_late_speech(monkeypatch):
    runtime = RecordingRuntime()
    interrupted = []
    runtime.interrupt = lambda **kw: interrupted.append(kw)
    engine = GemmaMultimodal(play=False, runtime=runtime, audio_mode="plain")
    spoken = []
    monkeypatch.setattr(engine, "_speak", spoken.append)

    def answer(*_):
        engine.force_listen()
        return "[OUTPUT:BOTH] this must not play"

    monkeypatch.setattr(engine, "_answer", answer)
    engine.send_text("first")
    assert interrupted == [{"session_key": engine.node_llm.session_key}]
    assert not spoken
    monkeypatch.setattr(engine, "_answer", lambda *_: "[OUTPUT:SPEECH] next reply")
    engine.send_text("second")
    assert spoken == ["next reply"]


def test_disconnected_runtime_cannot_prevent_playback_interruption():
    runtime = RecordingRuntime()

    def disconnect(**kwargs):
        raise ConnectionError("bridge disconnected")

    runtime.interrupt = disconnect
    engine = GemmaMultimodal(play=False, runtime=runtime, audio_mode="plain")
    calls = []
    from types import SimpleNamespace

    engine._io = SimpleNamespace(interrupt_playback=lambda: calls.append("stopped"))
    engine.force_listen()
    assert calls == ["stopped"]


def test_builtin_runtime_interrupt_is_session_scoped():
    from types import SimpleNamespace

    calls = []
    runtime = DefaultAgentRuntime.__new__(DefaultAgentRuntime)
    runtime._sessions = {
        "one": SimpleNamespace(interrupt=lambda: calls.append("one")),
        "two": SimpleNamespace(interrupt=lambda: calls.append("two")),
    }
    runtime.interrupt(session_key="missing")
    runtime.interrupt(session_key="one")
    assert calls == ["one"]
