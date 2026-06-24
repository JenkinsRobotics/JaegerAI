"""Avatar auto-state driver — flips Lilith's face emotion
automatically based on TTS lifecycle events on the bus.

Without this, the operator would have to manually fire
``set_avatar_state`` around every speak() call.  With it, the
avatar reacts in real-time to what the agent is doing:

    /act/speech    →  emotion = "speaking"  (lip-sync engages
                                              via TtsChunk)
    /sense/spoken  →  emotion = "neutral"   (back to idle)

Operator overrides win: if the brain calls ``set_avatar_state``
mid-speech (e.g. "speaking" → "focused" to express concentration),
the auto-driver's next switch will respect that until the next
TTS event.

The brain can still explicitly call ``set_avatar_state(emotion=)``
at any time — that AnimationCommand goes through the same bus
topic.  The auto-driver is just the default behaviour when no
one's explicitly setting state.
"""

from __future__ import annotations

import threading
from typing import Any

from jaeger_os.transport import topics
from jaeger_os.transport import Bus


class AvatarAutoStateDriver:
    """Subscribes to TTS lifecycle events; publishes
    AnimationCommands that swap the active emotion to match."""

    def __init__(
        self,
        *,
        bus: Bus,
        speaking_emotion: str = "speaking",
        idle_emotion: str = "neutral",
    ) -> None:
        self.bus = bus
        self.speaking_emotion = speaking_emotion
        self.idle_emotion = idle_emotion
        self._started = threading.Event()

    # ── lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        if self._started.is_set():
            return
        self.bus.subscribe(topics.ACT_SPEECH, self._on_speech_start)
        self.bus.subscribe(topics.SENSE_SPOKEN, self._on_speech_done)
        self._started.set()

    def stop(self) -> None:
        if not self._started.is_set():
            return
        try:
            self.bus.unsubscribe(topics.ACT_SPEECH, self._on_speech_start)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.bus.unsubscribe(topics.SENSE_SPOKEN, self._on_speech_done)
        except Exception:  # noqa: BLE001
            pass
        self._started.clear()

    # ── handlers ────────────────────────────────────────────────

    def _on_speech_start(self, msg: topics.TopicMessage) -> None:
        if not isinstance(msg, topics.SpeechCommand):
            return
        self._set_emotion(self.speaking_emotion)

    def _on_speech_done(self, msg: topics.TopicMessage) -> None:
        if not isinstance(msg, topics.SpokenAck):
            return
        self._set_emotion(self.idle_emotion)

    # ── publish ──────────────────────────────────────────────────

    def _set_emotion(self, emotion: str) -> None:
        """Publish an AnimationCommand for the given emotion.  Uses
        the same default expressions table as the
        ``set_avatar_state`` agent tool so explicit calls + auto-
        driver produce identical commands."""
        try:
            from jaeger_os.agent.tools.avatar import (
                _DEFAULT_EXPRESSIONS,
                _FRAMEWORK_AVATAR_DEFAULTS,
            )
        except Exception:  # noqa: BLE001
            return
        mapping = _DEFAULT_EXPRESSIONS.get(emotion)
        if mapping is None:
            return
        asset_path = str(_FRAMEWORK_AVATAR_DEFAULTS / mapping["asset"])
        try:
            self.bus.publish(topics.AnimationCommand(
                adapter=mapping["adapter"],
                asset_path=asset_path,
                duration_ms=0,
                params=dict(mapping.get("params", {})),
                node_id="avatar_auto",
            ))
        except Exception:  # noqa: BLE001
            pass
