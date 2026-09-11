"""Transducers package for ARES."""

from __future__ import annotations

from ..intent import CognitiveIntent, MediumType
from .acoustic_transducer import AcousticTransducer
from .base import MediumTransducer, TransductionResult
from .system_transducer import SystemTransducer
from .visual_transducer import VisualTransducer


class TransducerRegistry:
    """Manages available medium transducers and dispatches intents."""

    def __init__(self) -> None:
        self._transducers: dict[MediumType, MediumTransducer] = {
            MediumType.SYSTEM: SystemTransducer(),
            MediumType.VISUAL: VisualTransducer(),
            MediumType.ACOUSTIC: AcousticTransducer(),
        }

    def register(self, medium: MediumType, transducer: MediumTransducer) -> None:
        self._transducers[medium] = transducer

    async def broadcast(self, intent: CognitiveIntent) -> list[TransductionResult]:
        """Broadcasts intent across its designated medium (or all for multi-modal)."""
        results: list[TransductionResult] = []

        if intent.target_medium == MediumType.MULTI_MODAL:
            # Broadcast to visual + acoustic + system
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
