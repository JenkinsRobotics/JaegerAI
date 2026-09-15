"""Acoustic medium transducer for CoreAudio, tones, and synthesized speech.

Audio playback only when ``allow_notifications`` (or legacy ``enable_audio_play``) is True.
"""

from __future__ import annotations

import logging
import subprocess

from ..intent import CognitiveIntent, MediumType
from .base import TransductionResult

logger = logging.getLogger(__name__)

VALENCE_SOUND_MAP = {
    "urgent": "Sosumi",
    "analytical": "Bottle",
    "reassuring": "Purr",
    "celebratory": "Hero",
    "calm": "Tink",
}


class AcousticTransducer:
    """Transforms intent into acoustic envelopes; playback is opt-in."""

    def __init__(
        self,
        enable_audio_play: bool = False,
        *,
        allow_notifications: bool = False,
    ) -> None:
        # Either flag may enable playback; both default False (fail-closed).
        self.enable_audio_play = bool(enable_audio_play or allow_notifications)

    async def transduce(self, intent: CognitiveIntent) -> TransductionResult:
        sound_name = VALENCE_SOUND_MAP.get(intent.emotional_valence, "Tink")
        played = False

        if self.enable_audio_play and intent.salience >= 0.85:
            played = self._play_system_alert(sound_name)

        return TransductionResult(
            success=True,
            medium=MediumType.ACOUSTIC,
            output=f"Acoustic envelope generated (sound: {sound_name}, valence: {intent.emotional_valence})",
            metadata={
                "sound_name": sound_name,
                "played": played,
                "valence": intent.emotional_valence,
                "allow_audio": self.enable_audio_play,
            },
        )

    def _play_system_alert(self, sound_name: str) -> bool:
        try:
            subprocess.run(
                ["afplay", f"/System/Library/Sounds/{sound_name}.aiff"],
                timeout=2,
                capture_output=True,
            )
            return True
        except Exception:
            return False
