"""Client for a multimodal face attached to the native app's one brain."""

from __future__ import annotations

import base64
import json
import os
import queue
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np


class AttachedAgentRuntime:
    """AgentRuntime-compatible proxy over the bridge's private Unix socket.

    Camera capture stays with the face. JaegerAgent owns the live pipeline:
    duplex policy and playback remain methods of its engine, while Gemma,
    Whisper, Kokoro, memory, and tools are hosted in the already-running agent
    process. Opening another face therefore never loads another model stack.
    """

    vision_is_remote = True
    persistent_vision = True
    speech_is_remote = True

    def __init__(
        self, socket_path: str | Path | None = None, *, timeout: float = 180.0
    ) -> None:
        self.socket_path = (
            Path(socket_path) if socket_path else self.default_socket_path()
        )
        self.timeout = timeout
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._counter = 0
        self._event_sink: Callable[[dict[str, Any]], None] | None = None
        self._socket = self._connect()
        self._socket.settimeout(None)
        self._reader = self._socket.makefile("r", encoding="utf-8")
        self._writer = self._socket.makefile("w", encoding="utf-8")
        hello = self._read_frame()
        if hello.get("type") != "attached" or not hello.get("ok"):
            raise RuntimeError("Jaeger AI bridge refused the multimodal attachment")
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="multimodal-agent-events", daemon=True
        )
        self._reader_thread.start()

    @staticmethod
    def default_socket_path() -> Path:
        from jaeger_ai.core.instance.instance import (
            default_instance_name,
            resolve_instance_dir,
        )
        from jaeger_ai.interfaces.bridge import attached_face_socket_path

        instance = os.environ.get("JAEGER_INSTANCE_NAME") or default_instance_name()
        return attached_face_socket_path(resolve_instance_dir(instance))

    def _connect(self) -> socket.socket:
        deadline = time.monotonic() + min(self.timeout, 15.0)
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(self.timeout)
            try:
                client.connect(str(self.socket_path))
                return client
            except OSError as exc:
                last_error = exc
                client.close()
                time.sleep(0.1)
        raise RuntimeError(
            "The running Jaeger AI agent has no multimodal attachment endpoint at "
            f"{self.socket_path}: {last_error}"
        )

    def set_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        self._event_sink = sink

    def _read_frame(self) -> dict[str, Any]:
        raw = self._reader.readline()
        if not raw:
            raise ConnectionError("the Jaeger AI agent bridge disconnected")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TypeError("invalid attached-face frame")
        return value

    def _request(self, op: str, **payload: Any) -> dict[str, Any]:
        with self._pending_lock:
            self._counter += 1
            request_id = f"face-{self._counter}"
            response: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response
        message = {"op": op, "id": request_id, **payload}
        try:
            with self._write_lock:
                self._writer.write(json.dumps(message, ensure_ascii=False) + "\n")
                self._writer.flush()
            try:
                frame = response.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise TimeoutError(f"attached {op} request timed out") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if frame.get("type") == "result":
            if not frame.get("ok", False):
                raise RuntimeError(str(frame.get("error") or "attached request failed"))
            data = frame.get("data")
            return dict(data) if isinstance(data, dict) else {"data": data}
        return frame

    def _reader_loop(self) -> None:
        try:
            while True:
                frame = self._read_frame()
                request_id = str(frame.get("id") or "")
                target = None
                if request_id:
                    with self._pending_lock:
                        target = self._pending.get(request_id)
                if target is not None and frame.get("type") in {"reply", "result"}:
                    target.put(frame)
                elif self._event_sink is not None:
                    self._event_sink(frame)
        except (ConnectionError, json.JSONDecodeError, OSError, ValueError):
            return

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        return self._request(
            "turn", text=text, content=text, session=session_key, agentic_tools=True
        )

    def run_multimodal_turn(
        self,
        content: Any,
        *,
        text: str,
        system_prompt: str = "",
        session_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "turn",
            text=text,
            content=content,
            system_prompt=system_prompt,
            session=session_key,
            agentic_tools=True,
        )

    def run_chatbot_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        return self._request(
            "turn", text=text, content=text, session=session_key, agentic_tools=False
        )

    def run_chatbot_multimodal_turn(
        self,
        content: Any,
        *,
        text: str,
        system_prompt: str = "",
        session_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "turn",
            text=text,
            content=content,
            system_prompt=system_prompt,
            session=session_key,
            agentic_tools=False,
        )

    def configure_vision(self, handler: Any) -> None:
        self._request("vision", enabled=handler is not None and handler is not False)

    @staticmethod
    def _encode_pcm(audio: Any) -> str:
        samples = np.asarray(audio, dtype="<f4").reshape(-1)
        return base64.b64encode(samples.tobytes()).decode("ascii")

    def transcribe_audio(self, audio: Any, *, model: str) -> str:
        data = self._request("stt", pcm=self._encode_pcm(audio), model=model)
        return str(data.get("text") or "").strip()

    def synthesize_audio(self, text: str) -> np.ndarray:
        data = self._request("tts", text=text)
        raw = base64.b64decode(str(data.get("pcm") or ""), validate=True)
        return np.frombuffer(raw, dtype="<f4").copy()

    def make_stt_node(self, model: str) -> "RemoteSttNode":
        return RemoteSttNode(self, model=model)

    def make_tts_node(self) -> "RemoteTtsNode":
        return RemoteTtsNode(self)

    def warmup(self, *, session_key: str, system_prompt: str = "") -> bool:
        # The native bridge prewarms its real first-turn prefix during boot.
        return True

    warmup_chatbot = warmup

    def clear_session(self, session_key: str) -> None:
        self._request("clear", session=session_key, agentic_tools=True)

    def clear_chatbot_session(self, session_key: str) -> None:
        self._request("clear", session=session_key, agentic_tools=False)

    def health(self) -> dict[str, Any]:
        return self._request("health")

    def close(self) -> None:
        with self._write_lock:
            try:
                self._writer.write('{"op":"close"}\n')
                self._writer.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            for resource in (self._reader, self._writer, self._socket):
                try:
                    resource.close()
                except OSError:
                    pass


class _RemoteWhisperModel:
    """pywhispercpp-shaped view used by the full-duplex stream helper."""

    def __init__(self, node: "RemoteSttNode") -> None:
        self.node = node

    def transcribe(self, audio: Any, **_kwargs: Any) -> list[Any]:
        # Preview/full-duplex callers already hold the node lock. Calling the
        # node method here would acquire it twice; the bridge has the final
        # process-wide model/decode lock in either case.
        text = self.node.runtime.transcribe_audio(audio, model=self.node.model_name)
        duration_cs = int(np.asarray(audio).size / 16000 * 100)
        return [SimpleNamespace(text=text, t0=0, t1=duration_cs)] if text else []


class RemoteSttNode:
    """STT-node transport backed by JaegerAgent's prewarmed Whisper node."""

    def __init__(self, runtime: AttachedAgentRuntime, *, model: str) -> None:
        self.runtime = runtime
        self.model_name = model
        self._lock = threading.Lock()
        self.model = _RemoteWhisperModel(self)

    def load(self, say=print, *, model_name: str | None = None) -> None:
        if model_name:
            self.model_name = model_name
        say(f"using JaegerAgent-owned Whisper {self.model_name}")

    def transcribe(self, audio: Any) -> str:
        with self._lock:
            return self.runtime.transcribe_audio(audio, model=self.model_name)


class RemoteTtsNode:
    """TTS-node transport backed by JaegerAgent's prewarmed Kokoro node."""

    def __init__(self, runtime: AttachedAgentRuntime) -> None:
        self.runtime = runtime
        self.tts: object | None = None

    def load(self, say=print, **_kwargs: Any) -> None:
        self.tts = self
        say("using JaegerAgent-owned Kokoro")

    def synth(self, text: str):
        audio = self.runtime.synthesize_audio(text)
        if audio.size:
            yield audio


__all__ = ["AttachedAgentRuntime", "RemoteSttNode", "RemoteTtsNode"]
