"""Speech owned by JaegerAI interfaces, executed by the JaegerOS TTS slot.

Installer narration and a window's speaker button are interface behavior,
not actions chosen by the agent.  They therefore publish the same
``SpeechCommand`` contract as the agent's speech tool without importing the
Mind package.  The installed ``tts`` module owns synthesis and playback.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any


class UISpeech:
    """One interruptible interface-owned speech lane."""

    def __init__(self, *, timeout_s: float = 180.0) -> None:
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._active_correlation_id: str | None = None

    @property
    def active_correlation_id(self) -> str | None:
        with self._lock:
            return self._active_correlation_id

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

        runtime.ensure_tts_node()
        bus = runtime.get_bus()
        correlation_id = uuid.uuid4().hex
        command = topics.SpeechCommand(
            text=body,
            voice=str(voice or "").strip() or resolve_voice(),
            rate=float(rate),
            node_id="jaeger-ai-interface",
            correlation_id=correlation_id,
        )
        with self._lock:
            self._active_correlation_id = correlation_id
        try:
            ack = bus.request(
                command,
                ack_topic=topics.SENSE_SPOKEN,
                timeout_s=self.timeout_s,
            )
        finally:
            with self._lock:
                if self._active_correlation_id == correlation_id:
                    self._active_correlation_id = None
        if ack is None:
            return {
                "spoken": False,
                "reason": f"TTS node timeout after {self.timeout_s:g}s",
            }
        return {
            "spoken": bool(ack.ok),
            "elapsed_s": float(ack.duration_s),
            "reason": ack.reason,
            "correlation_id": correlation_id,
        }

    def stop(self) -> dict[str, Any]:
        """Interrupt this lane through the framework's correlation-safe stop."""
        correlation_id = self.active_correlation_id

        from jaeger_os.contract import topics
        from jaeger_os.nodes import runtime

        try:
            runtime.get_bus().publish(topics.SpeechStop(
                node_id="jaeger-ai-interface",
                correlation_id=correlation_id or "",
                reason="interface requested stop",
            ))
        except Exception:
            pass

        if correlation_id is None:
            return {"stopped": True, "active": False}

        return {
            "stopped": True,
            "active": True,
            "correlation_id": correlation_id,
        }


__all__ = ["UISpeech"]
