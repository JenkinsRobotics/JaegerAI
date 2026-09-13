"""One-brain attachment contract for the native multimodal face."""

from __future__ import annotations

import io
import queue
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from jaeger_ai.interfaces import bridge
from jaeger_ai.interfaces.pyside6.multimodal.remote_runtime import AttachedAgentRuntime


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run_multimodal_turn(self, content, *, text, system_prompt, session_key):
        from jaeger_agent.core.outputs import multimodal_output_active

        assert multimodal_output_active(), "output ownership must survive IPC"
        self.calls.append(("agentic", session_key))
        return {"text": f"saw:{text}:{len(content)}", "error": None}

    def run_chatbot_multimodal_turn(self, content, *, text, system_prompt, session_key):
        from jaeger_agent.core.outputs import multimodal_output_active

        assert multimodal_output_active()
        self.calls.append(("chatbot", session_key))
        return {"text": f"chat:{text}", "error": None}

    def health(self):
        return {"implementation": "same-brain", "model": "gemma.gguf"}

    def clear_session(self, session):
        self.calls.append(("clear-agentic", session))

    def clear_chatbot_session(self, session):
        self.calls.append(("clear-chatbot", session))


@pytest.mark.parametrize("cancellation_method", ["interrupt", "disconnect", "scope"])
def test_face_cancellation_reaches_active_loop_and_next_face_survives(tmp_path, cancellation_method):
    from jaeger_agent import JaegerAgent, Message, ProviderAdapter
    from jaeger_agent.core.cancellation import turn_cancellation

    started, cancelled = threading.Event(), threading.Event()
    owner_cancel = threading.Event()

    class Adapter(ProviderAdapter):
        name = "socket-cancel"

        def format_messages(self, messages, tools, system):
            return messages

        def call(self, formatted, interrupt_event, **kwargs):
            started.set()
            if interrupt_event.wait(3):
                cancelled.set()
            return Message(role="assistant", content="finished")

        def parse_response(self, raw):
            return raw

        def supports(self, feature):
            return False

    class Runtime(_Runtime):
        def run_multimodal_turn(self, content, *, text, system_prompt, session_key):
            if text == "long":
                return {"text": JaegerAgent(adapter=Adapter(), tools=[]).run_turn(text)}
            return {"text": "next face works"}

    ctx = bridge._Ctx()
    ctx.layout = SimpleNamespace(root=tmp_path)
    ctx.client, ctx.runtime = object(), Runtime()
    ctx.booted.set()
    turns, primary = queue.Queue(), io.StringIO()
    worker = threading.Thread(target=bridge._turn_worker, args=(primary, ctx, turns))
    worker.start()
    server = bridge._AttachedFaceServer(ctx, turns)
    server.start()
    client = AttachedAgentRuntime(server.path, timeout=5)
    other = AttachedAgentRuntime(server.path, timeout=5)
    outcomes = []

    def run():
        try:
            with turn_cancellation(owner_cancel):
                outcomes.append(client.run_multimodal_turn(
                    "long", text="long", system_prompt="test", session_key="one"))
        except ConnectionError:
            outcomes.append("disconnected")

    turn = threading.Thread(target=run)
    turn.start()
    try:
        assert started.wait(2)
        # Even with the same session name, another socket owns no such request.
        other.interrupt(session_key="one")
        assert not cancelled.wait(0.1)
        if cancellation_method == "disconnect":
            client.close()
        elif cancellation_method == "scope":
            owner_cancel.set()
        else:
            client.interrupt(session_key="one")
        assert cancelled.wait(2)
        turn.join(2)
        assert not turn.is_alive()
        assert outcomes
        assert other.run_multimodal_turn(
            "next", text="next", system_prompt="test", session_key="two"
        )["text"] == "next face works"
    finally:
        client.close()
        other.close()
        server.stop()
        turns.put(None)
        worker.join(4)
        turn.join(4)
    assert not worker.is_alive()


def test_cancelled_queued_turn_cannot_execute_slash_or_agent_work():
    cancelled = threading.Event()
    cancelled.set()
    ctx = bridge._Ctx()
    proto = io.StringIO()
    request = {"id": "one", "text": "/danger", "_cancel_event": cancelled}
    bridge._execute_turn(proto, ctx, request)
    assert "turn cancelled" in proto.getvalue()


def test_malformed_turn_cannot_kill_the_shared_worker():
    import json

    ctx = bridge._Ctx()
    ctx.runtime, ctx.client = _Runtime(), object()
    ctx.booted.set()
    turns, output = queue.Queue(), io.StringIO()
    turns.put({"id": "bad-text", "text": 123})
    turns.put({"id": "bad-token", "text": "hi", "_cancel_event": "not an event"})
    turns.put({"id": "good", "text": "hi", "system_prompt": "test", "engine_owned_output": True})
    turns.put(None)
    bridge._turn_worker(output, ctx, turns)
    replies = [json.loads(line) for line in output.getvalue().splitlines()
               if json.loads(line).get("type") == "reply"]
    assert [frame["id"] for frame in replies] == ["bad-text", "bad-token", "good"]
    assert all(frame.get("error") for frame in replies[:2])
    assert replies[-1]["text"] == "saw:hi:2"


def test_interrupt_does_not_wait_for_a_blocked_tts_chunk(tmp_path):
    started, release = threading.Event(), threading.Event()

    def synth(text):
        started.set()
        release.wait(3)  # simulates a non-interruptible native Kokoro call
        yield np.zeros(10, dtype=np.float32)

    ctx = bridge._Ctx()
    ctx.layout = SimpleNamespace(root=tmp_path)
    ctx.runtime, ctx.client = _Runtime(), object()
    ctx.speech = SimpleNamespace(synthesize_stream=synth)
    ctx.booted.set()
    server = bridge._AttachedFaceServer(ctx, queue.Queue())
    server.start()
    client = AttachedAgentRuntime(server.path, timeout=5)
    chunks, errors = [], []

    def consume():
        try:
            chunks.extend(client.stream_audio("cancel this"))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    try:
        assert started.wait(2)
        client.interrupt(session_key="multimodal")
        thread.join(1)
        assert not thread.is_alive()
        assert not chunks and not errors
    finally:
        release.set()
        thread.join(3)
        client.close()
        server.stop()


def test_attached_face_routes_both_modes_to_one_existing_runtime(tmp_path, monkeypatch):
    ctx = bridge._Ctx()
    ctx.layout = SimpleNamespace(root=tmp_path)
    ctx.client = object()
    ctx.runtime = _Runtime()
    ctx.booted.set()
    primary = io.StringIO()
    ctx.outputs.add(primary)
    turns = queue.Queue()
    worker = threading.Thread(target=bridge._turn_worker, args=(primary, ctx, turns))
    worker.start()
    server = bridge._AttachedFaceServer(ctx, turns)
    server.start()
    monkeypatch.setattr(
        bridge,
        "_configure_attached_vision",
        lambda _ctx, enabled: {"enabled": enabled, "ready": enabled},
    )

    client = AttachedAgentRuntime(server.path, timeout=5)
    try:
        content = [{"type": "image_url"}, {"type": "text", "text": "look"}]
        assert (
            client.run_multimodal_turn(
                content, text="look", system_prompt="system", session_key="multimodal"
            )["text"]
            == "saw:look:2"
        )
        assert (
            client.run_chatbot_multimodal_turn(
                "hello", text="hello", session_key="multimodal-chat", system_prompt=""
            )["text"]
            == "chat:hello"
        )
        assert client.health()["model"] == "gemma.gguf"
        client.configure_vision(True)
        client.clear_session("multimodal")
        client.clear_chatbot_session("multimodal-chat")
        assert ctx.runtime.calls == [
            ("agentic", "multimodal"),
            ("chatbot", "multimodal-chat"),
            ("clear-agentic", "multimodal"),
            ("clear-chatbot", "multimodal-chat"),
        ]
    finally:
        client.close()
        server.stop()
        turns.put(None)
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert not server.path.exists()


def test_attached_face_uses_jaeger_agent_speech_runtime(tmp_path):
    calls = []
    speech = SimpleNamespace(
        config=SimpleNamespace(stt_model="large-v3-turbo"),
        transcribe=lambda audio: calls.append(("stt", audio.shape)) or "heard",
        synthesize=lambda text: (
            calls.append(("tts", text)) or np.asarray([0.25, -0.25], dtype=np.float32)
        ),
    )

    ctx = bridge._Ctx()
    ctx.layout = SimpleNamespace(root=tmp_path)
    ctx.client = object()
    ctx.runtime = _Runtime()
    ctx.speech = speech
    ctx.booted.set()
    server = bridge._AttachedFaceServer(ctx, queue.Queue())
    server.start()
    client = AttachedAgentRuntime(server.path, timeout=5)
    try:
        assert (
            client.transcribe_audio(
                np.zeros(320, dtype=np.float32), model="large-v3-turbo"
            )
            == "heard"
        )
        assert client.synthesize_audio("hello").tolist() == [0.25, -0.25]
    finally:
        client.close()
        server.stop()

    assert calls == [
        ("stt", (320,)),
        ("tts", "hello"),
    ]


@pytest.fixture
def attached_speech(tmp_path):
    ctx = bridge._Ctx()
    ctx.layout = SimpleNamespace(root=tmp_path)
    ctx.client = object()
    ctx.runtime = _Runtime()
    ctx.speech = SimpleNamespace(config=SimpleNamespace(stt_model="large-v3-turbo"))
    ctx.booted.set()
    server = bridge._AttachedFaceServer(ctx, queue.Queue())
    server.start()
    client = AttachedAgentRuntime(server.path, timeout=3)
    try:
        yield ctx.speech, server, client
    finally:
        client.close()
        server.stop()


def test_first_audio_arrives_before_synthesis_finishes(attached_speech):
    speech, _, client = attached_speech
    continue_synthesis = threading.Event()
    completed = threading.Event()

    def synthesize_stream(text):
        assert text == "two sentences"
        yield np.asarray([0.25], dtype=np.float32)
        assert continue_synthesis.wait(2)
        yield np.asarray([-0.25], dtype=np.float32)
        completed.set()

    speech.synthesize_stream = synthesize_stream
    chunks = client.make_tts_node().synth("two sentences")
    try:
        assert next(chunks).tolist() == [0.25]
        assert not completed.is_set()
        continue_synthesis.set()
        assert next(chunks).tolist() == [-0.25]
        assert list(chunks) == []
        assert completed.is_set()
    finally:
        continue_synthesis.set()
        chunks.close()


def test_incremental_stt_preserves_segments_prompt_and_language(attached_speech):
    speech, _, client = attached_speech
    expected = [{"text": "first", "t0": 5, "t1": 70},
                {"text": " second", "t0": 95, "t1": 150}]

    def transcribe_segments(audio, **options):
        assert audio.shape == (32000,)
        assert options["language"] == "en"
        assert options["initial_prompt"] == "Prior sentence."
        assert not options["abort_callback"]()
        return expected

    speech.transcribe_segments = transcribe_segments
    model = client.make_stt_node("large-v3-turbo").model
    segments = model.transcribe(np.zeros(32000), language="en", initial_prompt="Prior sentence.")
    assert [vars(segment) for segment in segments] == expected


def test_stt_cancellation_reaches_decode_callback(attached_speech):
    speech, _, client = attached_speech
    started = threading.Event()
    aborted = threading.Event()
    cancel = threading.Event()

    def transcribe_segments(audio, *, abort_callback, **options):
        started.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if abort_callback():
                aborted.set()
                return []
            time.sleep(0.005)
        raise AssertionError("server decode never cancelled")

    speech.transcribe_segments = transcribe_segments
    result = []
    thread = threading.Thread(target=lambda: result.append(
        client.make_stt_node("large-v3-turbo").model.transcribe(
            np.zeros(320), abort_callback=cancel.is_set)))
    thread.start()
    try:
        assert started.wait(1)
        cancel.set()
        thread.join(1)
        assert not thread.is_alive()
        assert result == [[]]
        assert aborted.wait(1)
    finally:
        cancel.set()
        thread.join(2)


def test_disconnect_fails_pending_requests_without_waiting_for_timeout(attached_speech):
    speech, server, client = attached_speech
    started = threading.Event()
    release = threading.Event()

    def transcribe(audio):
        started.set()
        release.wait(2)
        return "late"

    speech.transcribe = transcribe
    errors = []

    def request():
        try:
            client.transcribe_audio(np.zeros(320), model="large-v3-turbo")
        except ConnectionError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=request)
    thread.start()
    try:
        assert started.wait(1)
        server.stop()
        thread.join(1)
        assert not thread.is_alive()
        assert errors and "disconnected" in errors[0]
        with pytest.raises(ConnectionError):
            client.health()
    finally:
        release.set()
        thread.join(2)


def test_audio_rejects_invalid_samples_and_model_mismatch(attached_speech):
    _, _, client = attached_speech
    with pytest.raises(RuntimeError, match="finite"):
        client.transcribe_audio([float("nan")], model="large-v3-turbo")
    with pytest.raises(RuntimeError, match="differs"):
        client.transcribe_audio([0.0], model="wrong-model")


def test_warmup_reaches_real_session_with_output_ownership(attached_speech):
    _, server, client = attached_speech
    calls = []

    def warmup(**kwargs):
        from jaeger_agent.core.outputs import multimodal_output_active

        assert multimodal_output_active()
        calls.append(kwargs)
        return True

    server.ctx.runtime.warmup = warmup
    server.ctx.runtime.warmup_chatbot = warmup
    assert client.warmup(session_key="voice", system_prompt="prompt")
    assert client.warmup_chatbot(session_key="chat", system_prompt="chat prompt")
    assert calls == [{"session_key": "voice", "system_prompt": "prompt"},
                     {"session_key": "chat", "system_prompt": "chat prompt"}]


def test_second_server_cannot_replace_live_endpoint(attached_speech):
    _, server, client = attached_speech
    duplicate = bridge._AttachedFaceServer(server.ctx, queue.Queue())
    with pytest.raises(RuntimeError, match="already has"):
        duplicate.start()
    duplicate.stop()
    assert server.path.exists()
    assert client.health()["model"] == "gemma.gguf"


def test_closing_face_during_turn_does_not_kill_shared_worker():
    ctx = bridge._Ctx()
    ctx.booted.set()
    ctx.client = object()
    ctx.runtime = SimpleNamespace(run_turn=lambda *args, **kwargs: {"text": "ok"})
    closed_face = io.StringIO()
    closed_face.close()
    primary = io.StringIO()
    turns = queue.Queue()
    turns.put(({"text": "old face"}, closed_face))
    turns.put({"text": "native chat"})
    turns.put(None)
    thread = threading.Thread(target=bridge._turn_worker, args=(primary, ctx, turns))
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    assert '"text": "ok"' in primary.getvalue()


def test_native_device_sample_rate_reaches_agent(attached_speech):
    speech, _, client = attached_speech
    calls = []
    speech.transcribe = lambda audio, **kwargs: calls.append((audio.size, kwargs)) or "native"
    data = client._request("stt", pcm=client._encode_pcm(np.zeros(480)), sample_rate=48000)
    assert data["text"] == "native"
    assert calls == [(480, {"sample_rate": 48000})]


def test_missing_projector_cannot_report_success(monkeypatch):
    from jaeger_agent.core import engine

    ctx = bridge._Ctx()
    ctx.runtime = _Runtime()
    closed = []
    node = SimpleNamespace(ready=False, load=lambda *args, **kwargs: None,
                           close=lambda: closed.append(True))
    monkeypatch.setattr(engine.vis_mod, "build", lambda: node)
    with pytest.raises(RuntimeError, match="projector is unavailable"):
        bridge._configure_attached_vision_locked(ctx, True)
    assert ctx.vision_node is None
    assert closed == [True]


def test_partially_booted_agent_does_not_report_healthy_or_decode(attached_speech):
    _, server, client = attached_speech
    server.ctx.boot_error = "Kokoro failed during boot"
    with pytest.raises(RuntimeError, match="Kokoro failed"):
        client.health()
    with pytest.raises(RuntimeError, match="Kokoro failed"):
        client.transcribe_audio([0.0], model="large-v3-turbo")
    with pytest.raises(RuntimeError, match="Kokoro failed"):
        client.warmup(session_key="voice")
