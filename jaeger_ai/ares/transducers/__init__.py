"""Transducers package for ARES (experimental heartbeat cognition)."""

from __future__ import annotations

from ..intent import CognitiveIntent, MediumType
from .acoustic_transducer import AcousticTransducer
from .base import MediumTransducer, TransductionResult
from .system_transducer import SystemTransducer
from .visual_transducer import VisualTransducer


class TransducerRegistry:
    """Manages available medium transducers and dispatches intents."""

    def __init__(self) -> None:
        # Defaults are fail-closed (no dangerous actions / notifications).
        self._transducers: dict[MediumType, MediumTransducer] = {
            MediumType.SYSTEM: SystemTransducer(allow_dangerous_actions=False),
            MediumType.VISUAL: VisualTransducer(allow_notifications=False),
            MediumType.ACOUSTIC: AcousticTransducer(enable_audio_play=False),
        }

    def register(self, medium: MediumType, transducer: MediumTransducer) -> None:
        self._transducers[medium] = transducer

    async def broadcast(self, intent: CognitiveIntent) -> list[TransductionResult]:
        """Broadcasts intent across its designated medium (or all for multi-modal)."""
        results: list[TransductionResult] = []

        if intent.target_medium == MediumType.MULTI_MODAL:
            for t in self._transducers.values():
                results.append(await t.transduce(intent))
        elif intent.target_medium in self._transducers:
            results.append(await self._transducers[intent.target_medium].transduce(intent))

        return results


__all__ = [
    "AcousticTransducer",
    "MediumTransducer",
    "SystemTransducer",
    "TransducerRegistry",
    "TransductionResult",
    "VisualTransducer",
]
