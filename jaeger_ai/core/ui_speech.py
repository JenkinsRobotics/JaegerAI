"""Speech owned by JaegerAI interfaces, executed by the JaegerOS TTS slot.

Installer narration and a window's speaker button are interface behavior,
not actions chosen by the agent.  They therefore publish the same
``SpeechCommand`` contract as the agent's speech tool without importing the
Mind package.  The installed ``tts`` module owns synthesis and playback.
"""

from __future__ import annotations

from collections import deque
import threading
import uuid
from typing import Any


class UISpeech:
    """One interruptible interface-owned speech lane."""

    def __init__(self, *, timeout_s: float = 180.0) -> None:
        self.timeout_s = timeout_s
        self._lock = threading.Condition()
        self._pending: deque[object] = deque()
        self._active: object | None = None
        self._epoch = 0
        self._active_bus: Any = None
        self._active_correlation_id: str | None = None
        # Keep exactly one timed-out request subscribed until its matching
        # receipt can be reconciled by the next status/Stop/speak call.
        self._unresolved: tuple[Any, Any, list[Any]] | None = None

    @property
    def active_correlation_id(self) -> str | None:
        with self._lock:
            self._reconcile_locked()
            return self._active_correlation_id

    def _reconcile_locked(self) -> None:
        if self._unresolved is None:
            return
        bus, callback, receipts = self._unresolved
        if not receipts:
            return
        bus.unsubscribe(receipts[0].topic, callback)
        self._unresolved = None
        self._active = None
        self._active_correlation_id = None
        self._active_bus = None
        self._lock.notify_all()

    def _unknown_result(self) -> dict[str, Any]:
        return {"spoken": False, "acknowledged": False,
                "execution_unknown": True,
                "correlation_id": self._active_correlation_id,
                "reason": "Previous UI speech has no matching receipt; new speech blocked"}

    def speak(self, text: str, *, voice: str = "", rate: float = 1.0) -> dict[str, Any]:
        """Speak through the configured JaegerOS TTS module and await its ack."""
        body = str(text or "").strip()
        if not body:
            return {"spoken": False, "reason": "nothing to speak"}
        if not 0.5 <= float(rate) <= 2.0:
            return {"spoken": False, "reason": "speech rate must be between 0.5 and 2.0"}

        from jaeger_os.contract import topics
        from jaeger_os.core.voice.voice_resolution import resolve_voice
        from jaeger_os.nodes import runtime

        # Admit one request per lane. Waiting requests never enter the shared
        # TTS queue, so Stop can discard this lane without a global stop.
        ticket = object()
        with self._lock:
            self._reconcile_locked()
            if self._unresolved is not None:
                return self._unknown_result()
            epoch = self._epoch
            self._pending.append(ticket)
            self._lock.notify_all()
            self._lock.wait_for(lambda: self._unresolved is not None or epoch != self._epoch or (
                self._active is None and self._pending[0] is ticket))
            if self._unresolved is not None and epoch == self._epoch:
                self._pending.remove(ticket)
                return self._unknown_result()
            if epoch != self._epoch:
                return {"spoken": False, "cancelled": True,
                        "reason": "interface speech cancelled before submission"}
            self._pending.popleft()
            self._active = ticket

        correlation_id = uuid.uuid4().hex
        acknowledged = threading.Event()
        received: list[Any] = []
        bus = None
        subscribed = False

        def on_ack(message: Any) -> None:
            if message.correlation_id == correlation_id:
                received.append(message)
                acknowledged.set()

        try:
            runtime.ensure_tts_node()
            bus = runtime.get_bus()
            command = topics.SpeechCommand(
                text=body,
                voice=str(voice or "").strip() or resolve_voice(),
                rate=float(rate),
                node_id="jaeger-ai-interface",
                correlation_id=correlation_id,
            )
            # Same subscribe/publish/wait contract as Bus.request, but make
            # publication atomic with local Stop. No stop-before-submit gap.
            with self._lock:
                if epoch != self._epoch:
                    return {"spoken": False, "cancelled": True,
                            "reason": "interface speech cancelled before submission"}
                bus.subscribe(topics.ACT_SPEECH_SPOKEN, on_ack)
                subscribed = True
                self._active_correlation_id = correlation_id
                self._active_bus = bus
                bus.publish(command)
            if not acknowledged.wait(self.timeout_s):
                with self._lock:
                    # A late ack may have arrived at the timeout boundary.
                    if not received:
                        self._unresolved = (bus, on_ack, received)
                        self._lock.notify_all()
                        return {"spoken": False, "acknowledged": False,
                                "execution_unknown": True, "correlation_id": correlation_id,
                                "reason": f"TTS node timeout after {self.timeout_s:g}s"}
            ack = received[0]
            with self._lock:
                cancelled = epoch != self._epoch
            return {
                "spoken": bool(ack.ok) and not cancelled,
                "acknowledged": True,
                "cancelled": cancelled,
                "elapsed_s": float(ack.duration_s),
                "reason": "interface speech cancelled" if cancelled else ack.reason,
                "correlation_id": correlation_id,
            }
        finally:
            with self._lock:
                # A concurrent status call may already have reconciled a late
                # receipt. Only the still-owning invocation cleans this lease.
                if self._active is ticket and self._unresolved is None:
                    try:
                        if subscribed:
                            bus.unsubscribe(topics.ACT_SPEECH_SPOKEN, on_ack)
                    finally:
                        self._active = None
                        self._active_correlation_id = None
                        self._active_bus = None
                        self._lock.notify_all()

    def stop(self) -> dict[str, Any]:
        """Discard pending lane work and request a scoped active stop.

        Publication is not a playback acknowledgement. Never issue a blank
        correlation ID: that would stop unrelated producers on the TTS bus.
        """
        from jaeger_os.contract import topics

        with self._lock:
            self._reconcile_locked()
            self._epoch += 1
            discarded = len(self._pending)
            self._pending.clear()
            self._lock.notify_all()
            correlation_id = self._active_correlation_id
            if correlation_id is None:
                return {"stopped": self._active is None,
                        "active": self._active is not None,
                        "discarded": discarded}
            try:
                self._active_bus.publish(topics.SpeechStop(
                    node_id="jaeger-ai-interface",
                    correlation_id=correlation_id,
                    reason="interface requested stop",
                ))
            except Exception as exc:
                return {"stopped": False, "active": True,
                        "stop_requested": False, "discarded": discarded,
                        "execution_unknown": self._unresolved is not None,
                        "correlation_id": correlation_id, "error": str(exc)}
            return {"stopped": False, "active": True,
                    "stop_requested": True, "acknowledged": False,
                    "execution_unknown": self._unresolved is not None,
                    "discarded": discarded, "correlation_id": correlation_id}


__all__ = ["UISpeech"]
