"""Qt pump for :mod:`jaeger_agent`.

This module deliberately owns no audio or turn policy.  It moves three input
queues into the headless engine and translates the engine's complete Event
contract into Qt signals.  Unknown event kinds raise so a new engine surface
cannot silently disappear from the GUI.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import QThread, Signal


EVENT_KINDS = frozenset(
    {
        "user",
        "assistant",
        "overheard",
        "environment",
        "self",
        "submitted",
        "session",
        "status",
        "state",
        "live",
        "latency",
        "audio",
        "mic",
    }
)


class BorrowedRuntime:
    """Forward engine calls without giving it ownership of JaegerAI's core."""

    def __init__(self, runtime: Any, *, agentic_tools: bool = True) -> None:
        self.runtime = runtime
        self.agentic_tools = agentic_tools
        self.vision_is_remote = bool(getattr(runtime, "vision_is_remote", False))
        self.persistent_vision = bool(getattr(runtime, "persistent_vision", False))

    def run_turn(self, text: str, *, session_key: str) -> Any:
        if not self.agentic_tools:
            method = getattr(self.runtime, "run_chatbot_turn", None)
            if callable(method):
                return method(text, session_key=session_key)
        return self.runtime.run_turn(text, session_key=session_key)

    def run_multimodal_turn(
        self,
        content: Any,
        *,
        text: str,
        system_prompt: str,
        session_key: str,
    ) -> Any:
        if not self.agentic_tools:
            chatbot = getattr(self.runtime, "run_chatbot_multimodal_turn", None)
            if not callable(chatbot):
                raise RuntimeError(
                    "JaegerAI's tool-free chatbot lane is unavailable; "
                    "jaeger-agent 1.2.0 and JaegerAI 0.12.0 must be installed together"
                )
            return chatbot(
                content,
                text=text,
                system_prompt=system_prompt,
                session_key=session_key,
            )
        method = getattr(self.runtime, "run_multimodal_turn", None)
        if not callable(method):
            if isinstance(content, str):
                return self.run_turn(content, session_key=session_key)
            raise RuntimeError(
                "JaegerAI's AgentRuntime does not support image turns; "
                "jaeger-agent 1.2.0 and JaegerAI 0.12.0 must be installed together"
            )
        return method(
            content,
            text=text,
            system_prompt=system_prompt,
            session_key=session_key,
        )

    def configure_vision(self, chat_handler: Any) -> None:
        method = getattr(self.runtime, "configure_vision", None)
        if callable(method):
            method(chat_handler)

    def warmup(self, *, session_key: str, system_prompt: str = "") -> bool:
        name = "warmup" if self.agentic_tools else "warmup_chatbot"
        method = getattr(self.runtime, name, None)
        if not callable(method):
            return False
        return bool(method(session_key=session_key, system_prompt=system_prompt))

    def clear_session(self, session_key: str) -> None:
        name = "clear_session" if self.agentic_tools else "clear_chatbot_session"
        method = getattr(self.runtime, name, None)
        if callable(method):
            method(session_key)

    def health(self) -> dict[str, Any]:
        method = getattr(self.runtime, "health", None)
        return dict(method() or {}) if callable(method) else {}

    def close(self) -> None:
        """The chassis owns the borrowed runtime and closes it at app exit."""
        # The engine has just closed its native projector. Detach that stale
        # handler from the shared Llama object without closing JaegerAI's
        # process-owned runtime or model.
        method = getattr(self.runtime, "configure_vision", None)
        if callable(method) and not self.persistent_vision:
            method(None)


class MultimodalWorker(QThread):
    """Own three queues and pump them into one multimodal engine."""

    status = Signal(str)
    ready = Signal()
    commit = Signal(int, str, str)
    output = Signal(str, object)
    failed = Signal(str)
    summary = Signal(str)
    telem = Signal(str, str)
    lat = Signal(str, object)
    live = Signal(str)
    tscript = Signal(str, str)
    spoke = Signal(object)
    heard = Signal(object)

    def __init__(
        self,
        *,
        runtime: Any = None,
        engine_factory: Callable[..., Any] | None = None,
        want_vision: bool = False,
        extra_prompt: str = "",
        audio_mode: str = "structured",
        barge_mode: str = "stop",
        agentic_tools: bool = True,
        output_mode: str | None = None,
    ) -> None:
        super().__init__()
        if audio_mode not in {"plain", "structured", "quasi", "full"}:
            raise ValueError("audio_mode must be plain|structured|quasi|full")
        if barge_mode not in {"stop", "continue"}:
            raise ValueError("barge_mode must be stop|continue")
        output_mode = output_mode or ("dynamic" if agentic_tools else "speech")
        if output_mode not in {"dynamic", "speech", "text", "mirror"}:
            raise ValueError("output_mode must be dynamic|speech|text|mirror")
        self.audio_q: queue.Queue[np.ndarray] = queue.Queue()
        self.text_q: queue.Queue[str] = queue.Queue()
        self.image_q: queue.Queue[str] = queue.Queue()
        self._stop_evt = threading.Event()
        self.audio_mode = audio_mode
        self.barge_mode = barge_mode
        self.agentic_tools = agentic_tools
        self.output_mode = output_mode
        self.gui_feeds_audio = audio_mode in {"plain", "structured"}
        if engine_factory is None:
            from jaeger_agent import MultimodalAgent

            engine_factory = MultimodalAgent
        remote_vision = bool(
            runtime is not None and getattr(runtime, "vision_is_remote", False)
        )
        if remote_vision and want_vision:
            # The projector must live beside the shared Llama instance. Asking
            # the bridge to load it avoids a useless second Metal projector in
            # this UI process while image composition remains in the engine.
            runtime.configure_vision(True)
        kwargs: dict[str, Any] = {
            "on_event": self._on_event,
            "want_vision": want_vision and not remote_vision,
            "extra_prompt": extra_prompt,
            "half_duplex": self.gui_feeds_audio,
            "audio_mode": audio_mode,
            "output_mode": output_mode,
        }
        if runtime is not None:
            kwargs["runtime"] = BorrowedRuntime(runtime, agentic_tools=agentic_tools)
        self.engine = engine_factory(**kwargs)
        if runtime is not None and getattr(runtime, "speech_is_remote", False):
            # The face owns capture/playback, never a second Whisper/Kokoro.
            # Install the bridge-backed node shapes before engine.load().
            self.engine.node_stt = runtime.make_stt_node(self.engine.config.stt_model)
            self.engine.node_tts = runtime.make_tts_node()
            self.engine._stt_lock = self.engine.node_stt._lock
        self.engine.drain_input = self._drain_audio
        self._index = 0
        self._turns = 0

    def _drain_audio(self) -> None:
        with self.audio_q.mutex:
            self.audio_q.queue.clear()

    def stop(self) -> None:
        self._stop_evt.set()
        # Cut any active playback so the pump can reach engine.close promptly.
        # This remains an engine hook: the worker does not implement floor logic.
        method = getattr(self.engine, "force_listen", None)
        if callable(method):
            try:
                method()
            except Exception:  # noqa: BLE001 — stop must stay teardown-safe
                pass

    def submit_text(self, text: str) -> None:
        self.text_q.put(text)

    def submit_image(self, data_uri: str) -> None:
        self.image_q.put(data_uri)

    def set_paused(self, paused: bool) -> None:
        method = getattr(self.engine, "set_paused", None)
        if not callable(method):
            raise RuntimeError("jaeger-agent 1.2.0 set_paused() hook is unavailable")
        method(paused)

    def set_barge_mode(self, mode: str) -> None:
        if mode not in {"stop", "continue"}:
            raise ValueError("barge mode must be stop or continue")
        self.barge_mode = mode
        method = getattr(self.engine, "set_barge_mode", None)
        if not callable(method):
            raise RuntimeError(
                "jaeger-agent 1.2.0 set_barge_mode() hook is unavailable"
            )
        method(mode)

    def set_agentic_tools(self, enabled: bool) -> None:
        """Switch the next turn between the shared agentic/chatbot lanes."""
        self.agentic_tools = bool(enabled)
        brain = getattr(self.engine, "node_llm", None)
        borrowed = getattr(brain, "runtime", None)
        if borrowed is not None and hasattr(borrowed, "agentic_tools"):
            borrowed.agentic_tools = self.agentic_tools
        output_mode = "dynamic" if self.agentic_tools else "speech"
        self.output_mode = output_mode
        config = getattr(self.engine, "config", None)
        copy = getattr(config, "model_copy", None)
        if callable(copy):
            self.engine.config = copy(update={"output_mode": output_mode})

    def force_listen(self) -> None:
        method = getattr(self.engine, "force_listen", None)
        if not callable(method):
            raise RuntimeError("jaeger-agent 1.2.0 force_listen() hook is unavailable")
        method()

    @property
    def speaking(self) -> Any:
        return self.engine.speaking

    def _on_event(self, event: Any) -> None:
        kind = str(getattr(event, "kind", ""))
        if kind not in EVENT_KINDS:
            raise ValueError(f"unmapped multimodal Event kind: {kind!r}")
        if kind == "user":
            self._index += 1
            self.commit.emit(self._index, kind, str(event.text))
            self.tscript.emit("committed", str(event.text))
        elif kind == "assistant":
            data = event.data if isinstance(event.data, dict) else {}
            display = bool(data.get("display", bool(event.text)))
            channels = tuple(data.get("channels") or (("text",) if display else ()))
            if display and str(event.text):
                self._index += 1
                self.commit.emit(self._index, kind, str(event.text))
            self._turns += 1
            label = "+".join(str(channel) for channel in channels).upper() or "SILENT"
            self.output.emit(label, dict(data))
        elif kind in {"overheard", "environment", "self", "submitted"}:
            self.tscript.emit(kind, str(event.text))
        elif kind == "session":
            self.telem.emit(str(event.text), str(event.data))
        elif kind == "status":
            self.status.emit(str(event.text))
        elif kind == "state":
            self.telem.emit("Now", str(event.text))
        elif kind == "live":
            self.live.emit(str(event.text))
        elif kind == "latency":
            self.lat.emit(str(event.text), event.data)
        elif kind == "audio":
            self.spoke.emit(event.data)
        elif kind == "mic":
            self.heard.emit(event.data)

    def _emit_session_facts(self) -> None:
        from jaeger_agent.core import policy

        config = self.engine.config
        health: dict[str, Any] = {}
        node_llm = getattr(self.engine, "node_llm", None)
        borrowed = getattr(node_llm, "runtime", None)
        health_method = getattr(borrowed, "health", None)
        if callable(health_method):
            health = dict(health_method() or {})
        model = str(health.get("model") or config.fallback_llm_model_path)
        self.telem.emit("Wake phrase", "hey jaeger")
        self.telem.emit("Mode", f"{self.audio_mode.upper()} AUDIO")
        self.telem.emit("Model", model)
        self.telem.emit("Microphone", "ENGINE" if not self.gui_feeds_audio else "GUI")
        self.telem.emit(
            "Gate",
            f"Silero {policy.SILERO_OPEN_P:.3f}/{policy.SILERO_CLOSE_P:.3f}",
        )
        self.telem.emit("Audio", self.audio_mode.upper())
        self.telem.emit("Barge", self.barge_mode)
        self.telem.emit("Agent", "AGENTIC" if self.agentic_tools else "CHATBOT")
        self.telem.emit("Output", self.output_mode.upper())
        self.telem.emit("Endpoint", f"{policy.SILENCE_HANGOVER_MS} ms silence")

    def run(self) -> None:
        failure = ""
        try:
            self.engine.set_barge_mode(self.barge_mode)
            self.engine.load()
            self._emit_session_facts()
            self.ready.emit()
            while not self._stop_evt.is_set():
                try:
                    self.engine.attach_image(self.image_q.get_nowait())
                except queue.Empty:
                    pass
                try:
                    self.engine.send_text(self.text_q.get_nowait())
                    continue
                except queue.Empty:
                    pass
                try:
                    frame = self.audio_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self.gui_feeds_audio:
                    self.engine.push_audio(frame)
        except Exception as exc:  # noqa: BLE001 — surface must report worker failure
            failure = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self.engine.close()
            except Exception as exc:  # noqa: BLE001 — report teardown, do not leak thread
                self.status.emit(f"engine close warning: {type(exc).__name__}: {exc}")
            self.summary.emit(f"{self._turns} turns · {self.audio_mode} audio pipeline")
            if failure:
                # Emit this last so a close warning cannot erase the useful
                # startup/runtime failure from the window's status line.
                self.failed.emit(failure)
            else:
                self.status.emit("session ended")


__all__ = ["BorrowedRuntime", "EVENT_KINDS", "MultimodalWorker"]
