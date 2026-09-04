"""One-brain attachment contract for the native multimodal face."""

from __future__ import annotations

import io
import importlib
import queue
import threading
from types import SimpleNamespace

import numpy as np

from jaeger_ai.interfaces import bridge
from jaeger_ai.interfaces.pyside6.multimodal.remote_runtime import AttachedAgentRuntime


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run_multimodal_turn(self, content, *, text, system_prompt, session_key):
        self.calls.append(("agentic", session_key))
        return {"text": f"saw:{text}:{len(content)}", "error": None}

    def run_chatbot_multimodal_turn(self, content, *, text, system_prompt, session_key):
        self.calls.append(("chatbot", session_key))
        return {"text": f"chat:{text}", "error": None}

    def health(self):
        return {"implementation": "same-brain", "model": "gemma.gguf"}

    def clear_session(self, session):
        self.calls.append(("clear-agentic", session))

    def clear_chatbot_session(self, session):
        self.calls.append(("clear-chatbot", session))


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


def test_attached_face_borrows_bridge_whisper_and_kokoro(tmp_path, monkeypatch):
    from jaeger_os.nodes import runtime as node_runtime

    listen_module = importlib.import_module("jaeger_agent.tools.listen")
    calls = []
    monkeypatch.setattr(
        listen_module,
        "transcribe_samples",
        lambda audio, model: calls.append(("stt", model, audio.shape)) or "heard",
    )
    synth = SimpleNamespace(
        render=lambda text: (
            calls.append(("tts", text)) or np.asarray([0.25, -0.25], dtype=np.float32)
        )
    )
    monkeypatch.setattr(node_runtime, "get_synth", lambda: synth)

    ctx = bridge._Ctx()
    ctx.layout = SimpleNamespace(root=tmp_path)
    ctx.client = object()
    ctx.runtime = _Runtime()
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
        ("stt", "large-v3-turbo", (320,)),
        ("tts", "hello"),
    ]
