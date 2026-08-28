"""Headless bus bridge for any runtime implementing ``AgentRuntime``."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from jaeger_os.contract import topics

from .contracts import AgentRuntime, RuntimeEvents, normalize_turn_result
from .messages import (
    CHAT_INPUT_TOPIC,
    AgentActivity,
    AgentState,
    ChatReply,
    ToolEvent,
)

_DEFAULT_MAX_QUEUE = 32
_TRANSCRIPT_TOPIC = (
    getattr(topics, "SENSE_STT_TRANSCRIPT", None)
    or getattr(topics, "SENSE_TRANSCRIPT")
)


class BusRuntimeEvents(RuntimeEvents):
    """Translate engine progress callbacks into public bus messages."""

    def __init__(self, publish: Callable[[Any], None]) -> None:
        self._publish = publish
        self.current_session = ""

    def activity(self, kind: str, text: str, *, session: str = "") -> None:
        self._publish(
            AgentActivity(kind=str(kind), text=str(text), session=session or self.current_session)
        )

    def tool(
        self,
        name: str,
        phase: str,
        *,
        elapsed_s: float = 0.0,
        detail: str = "",
        session: str = "",
    ) -> None:
        self._publish(
            ToolEvent(
                name=str(name),
                phase=str(phase),
                elapsed_s=float(elapsed_s),
                detail=str(detail),
                session=session or self.current_session,
            )
        )


class AgentBridge:
    """Run agent turns off the bus delivery thread and publish their results."""

    def __init__(
        self,
        *,
        bus: Any,
        runtime: AgentRuntime,
        session_key: str = "default",
        max_queue: int = _DEFAULT_MAX_QUEUE,
        publish: Callable[[Any], None] | None = None,
        subscribe: Callable[[str, Callable[..., None]], None] | None = None,
        unsubscribe: Callable[[str, Callable[..., None]], None] | None = None,
    ) -> None:
        self.bus = bus
        self.runtime = runtime
        # Transitional convenience for hosts that previously reached the
        # concrete model client through their application-owned bridge.
        self.client = getattr(runtime, "client", None)
        self.session_key = session_key
        self._publish = publish or bus.publish
        self._subscribe = subscribe or bus.subscribe
        self._unsubscribe = unsubscribe or getattr(bus, "unsubscribe", lambda *_: None)
        self._inbox: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._accepting = threading.Event()
        self._turn_active = threading.Event()
        self._events = BusRuntimeEvents(self._publish)
        self._state = "created"
        self._last_error: str | None = None
        self.turns = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        start = getattr(self.runtime, "start", None)
        if callable(start):
            start(events=self._events, bus=self.bus)
        self._subscribe(CHAT_INPUT_TOPIC, self._on_chat)
        self._subscribe(_TRANSCRIPT_TOPIC, self._on_transcript)
        self._accepting.set()
        self._thread = threading.Thread(target=self._loop, name="jaeger-agent", daemon=True)
        self._thread.start()
        self._publish_state("idle")

    def stop(self) -> None:
        if not self._accepting.is_set() and self._stop.is_set():
            return
        self._accepting.clear()
        self._stop.set()
        self._unsubscribe(CHAT_INPUT_TOPIC, self._on_chat)
        self._unsubscribe(_TRANSCRIPT_TOPIC, self._on_transcript)

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def close(self) -> None:
        """Drain the bridge before releasing the runtime's model/resources."""

        self.stop()
        self.join(timeout=30.0)
        self.runtime.close()

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self._state,
            "agent_state": self._state,
            "turns": self.turns,
            "queue_depth": self._inbox.qsize(),
            "turn_active": self._turn_active.is_set(),
            "last_error": self._last_error,
        }
        runtime_health = getattr(self.runtime, "health", None)
        if callable(runtime_health):
            result["runtime"] = runtime_health()
        return result

    def _on_chat(self, message: Any) -> None:
        session = getattr(message, "session", "") or self.session_key
        self._enqueue(getattr(message, "text", ""), session)

    def _on_transcript(self, message: Any) -> None:
        if not getattr(message, "is_final", True):
            return
        self._enqueue(getattr(message, "text", ""), self.session_key)

    def _enqueue(self, text: str, session: str) -> None:
        if not self._accepting.is_set():
            return
        text = (text or "").strip()
        if not text:
            return
        steer = getattr(self.runtime, "steer", None)
        if self._turn_active.is_set() and callable(steer) and bool(steer(text)):
            return
        try:
            self._inbox.put_nowait((text, session))
        except queue.Full:
            self._publish(ChatReply(text="(busy — finishing the previous turn…)", session=session))

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    text, session = self._inbox.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._events.current_session = session
                self._turn_active.set()
                self.turns += 1
                self._publish_state("thinking", session)
                try:
                    result = normalize_turn_result(
                        self.runtime.run_turn(text, session_key=session)
                    )
                    reply = f"(agent error: {result.error})" if result.error else result.text
                    self._last_error = result.error
                except Exception as exc:  # noqa: BLE001 - one bad turn must not kill the mind
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    self._publish_state("error", session)
                    reply = f"(turn failed: {self._last_error})"
                finally:
                    self._turn_active.clear()
                    self._events.current_session = ""
                self._publish(ChatReply(text=reply, session=session))
                self._publish_state("idle", session, self._context_detail(session))
        finally:
            self._state = "stopped"

    def _context_detail(self, session: str) -> str:
        context_detail = getattr(self.runtime, "context_detail", None)
        if not callable(context_detail):
            return ""
        try:
            return str(context_detail(session) or "")
        except Exception:  # noqa: BLE001 - status enrichment is best effort
            return ""

    def _publish_state(self, state: str, session: str = "", detail: str = "") -> None:
        self._state = state
        self._publish(AgentState(state=state, detail=detail, session=session))


__all__ = ["AgentBridge", "BusRuntimeEvents"]
