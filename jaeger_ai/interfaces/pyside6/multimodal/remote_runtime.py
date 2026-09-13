"""Client for a multimodal face attached to the native app's one brain."""

from __future__ import annotations

import base64
import json
import logging
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
        self._turn_requests: dict[str, str] = {}
        self._request_interrupts: dict[str, threading.Event] = {}
        self._closed = threading.Event()
        self._counter = 0
        self._event_sink: Callable[[dict[str, Any]], None] | None = None
        self._socket = self._connect()
        self._reader = self._socket.makefile("r", encoding="utf-8")
        self._writer = self._socket.makefile("w", encoding="utf-8")
        try:
            hello = self._read_frame()
            if hello.get("type") != "attached" or not hello.get("ok"):
                raise RuntimeError("Jaeger AI bridge refused the multimodal attachment")
        except Exception:
            self.close()
            raise
        self._socket.settimeout(None)
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

    def _send(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            if self._closed.is_set():
                raise ConnectionError("the Jaeger AI agent bridge disconnected")
            self._writer.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._writer.flush()

    def _request_frames(self, op: str, *, abort_callback=None, **payload: Any):
        from jaeger_agent.core.cancellation import current_cancellation

        turn_cancel = current_cancellation() if op in {"turn", "stt", "tts"} else None

        def aborted():
            return (local_abort.is_set()
                    or (turn_cancel is not None and turn_cancel.is_set())
                    or (abort_callback is not None and abort_callback()))

        if op == "turn":
            payload["engine_owned_output"] = True
        local_abort = threading.Event()
        with self._pending_lock:
            if self._closed.is_set():
                raise ConnectionError("the Jaeger AI agent bridge disconnected")
            self._counter += 1
            request_id = f"face-{self._counter}"
            response: queue.Queue[dict[str, Any]] = queue.Queue()
            self._pending[request_id] = response
            if op == "turn":
                self._turn_requests[request_id] = str(payload.get("session") or "desktop-app")
            if op in {"turn", "tts"}:
                self._request_interrupts[request_id] = local_abort
        complete = False
        try:
            if aborted():
                return
            self._send({"op": op, "id": request_id, **payload})
            deadline = time.monotonic() + self.timeout
            while True:
                if aborted():
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"attached {op} request timed out")
                try:
                    frame = response.get(timeout=min(remaining, 0.05))
                except queue.Empty:
                    continue
                if frame.get("type") == "disconnected":
                    raise ConnectionError(str(frame["error"]))
                complete = frame.get("type") in {"result", "reply"}
                if frame.get("type") == "result" and not frame.get("ok", False):
                    raise RuntimeError(str(frame.get("error") or "attached request failed"))
                yield frame
                if complete:
                    return
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
                self._turn_requests.pop(request_id, None)
                self._request_interrupts.pop(request_id, None)
            if not complete:
                try:
                    self._send({"op": "cancel", "target": request_id})
                except (OSError, ValueError):
                    pass

    def _request(self, op: str, **payload: Any) -> dict[str, Any]:
        for frame in self._request_frames(op, **payload):
            if frame.get("type") == "result":
                data = frame.get("data")
                return dict(data) if isinstance(data, dict) else {"data": data}
            if frame.get("type") == "reply":
                return frame
        return {}

    def _disconnect(self) -> None:
        with self._pending_lock:
            self._closed.set()
            for target in self._pending.values():
                target.put({"type": "disconnected", "error": "the Jaeger AI agent bridge disconnected"})

    def _reader_loop(self) -> None:
        try:
            while True:
                frame = self._read_frame()
                request_id = str(frame.get("id") or "")
                target = None
                if request_id:
                    with self._pending_lock:
                        target = self._pending.get(request_id)
                if target is not None and frame.get("type") in {"reply", "result", "audio_chunk"}:
                    target.put(frame)
                elif self._event_sink is not None:
                    try:
                        self._event_sink(frame)
                    except Exception:
                        # UI observers cannot take down transport or strand requests.
                        logging.getLogger(__name__).exception("attached-face event observer failed")
        except (ConnectionError, json.JSONDecodeError, OSError, ValueError):
            pass
        finally:
            self._disconnect()

    def interrupt(self, *, session_key: str) -> None:
        """Cancel this face's pending turns in one session, never another face."""
        with self._pending_lock:
            targets = []
            for key, event in self._request_interrupts.items():
                if key not in self._turn_requests or self._turn_requests[key] == session_key:
                    event.set()
                    targets.append(key)
            # Local events also close the race where interruption arrives
            # between registration and send: the request is either never sent
            # or its finally block sends cancel AFTER the turn on the socket.
        for key in targets:
            self._send({"op": "cancel", "target": key})

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

    def transcribe_segments(self, audio: Any, *, model: str, **options: Any) -> list[Any]:
        abort_callback = options.pop("abort_callback", None)
        # Callbacks stay in their owning process. Cancellation is signalled
        # separately; real timestamps and serializable decode options cross IPC.
        data = self._request(
            "stt", pcm=self._encode_pcm(audio), model=model, segments=True,
            options=options, abort_callback=abort_callback,
        )
        return [SimpleNamespace(**segment) for segment in data.get("segments", [])]

    def stream_audio(self, text: str):
        frames = self._request_frames("tts", text=text, stream=True)
        try:
            for frame in frames:
                if frame.get("type") == "audio_chunk":
                    raw = base64.b64decode(frame["pcm"], validate=True)
                    yield np.frombuffer(raw, dtype="<f4").copy()
        finally:
            frames.close()

    def synthesize_audio(self, text: str) -> np.ndarray:
        data = self._request("tts", text=text)
        raw = base64.b64decode(str(data.get("pcm") or ""), validate=True)
        return np.frombuffer(raw, dtype="<f4").copy()

    def make_stt_node(self, model: str) -> RemoteSttNode:
        return RemoteSttNode(self, model=model)

    def make_tts_node(self) -> RemoteTtsNode:
        return RemoteTtsNode(self)

    def warmup(self, *, session_key: str, system_prompt: str = "") -> bool:
        return bool(self._request("warmup", session=session_key,
                                  system_prompt=system_prompt, agentic_tools=True).get("warmed"))

    def warmup_chatbot(self, *, session_key: str, system_prompt: str = "") -> bool:
        return bool(self._request("warmup", session=session_key,
                                  system_prompt=system_prompt, agentic_tools=False).get("warmed"))

    def clear_session(self, session_key: str) -> None:
        self._request("clear", session=session_key, agentic_tools=True)

    def clear_chatbot_session(self, session_key: str) -> None:
        self._request("clear", session=session_key, agentic_tools=False)

    def health(self) -> dict[str, Any]:
        return self._request("health")

    def close(self) -> None:
        self._disconnect()
        # Wake a blocked readline BEFORE closing its buffered file object.
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        reader_thread = getattr(self, "_reader_thread", None)
        if reader_thread is not None and reader_thread is not threading.current_thread():
            reader_thread.join(timeout=2)
        with self._write_lock:
            for resource in (self._reader, self._writer, self._socket):
                try:
                    resource.close()
                except OSError:
                    pass


class _RemoteWhisperModel:
    """pywhispercpp-shaped view used by the full-duplex stream helper."""

    def __init__(self, node: RemoteSttNode) -> None:
        self.node = node

    def transcribe(self, audio: Any, **kwargs: Any) -> list[Any]:
        # Preview/full-duplex callers already hold the node lock. Calling the
        # node method here would acquire it twice; the bridge has the final
        # process-wide model/decode lock in either case.
        return self.node.runtime.transcribe_segments(
            audio, model=self.node.model_name, **kwargs
        )


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
        yield from self.runtime.stream_audio(text)


__all__ = ["AttachedAgentRuntime", "RemoteSttNode", "RemoteTtsNode"]
