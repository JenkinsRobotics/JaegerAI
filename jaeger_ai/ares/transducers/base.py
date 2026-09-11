"""Base protocol and data structures for ARES medium transducers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..intent import CognitiveIntent, MediumType


@dataclass
class TransductionResult:
    success: bool
    medium: MediumType
    output: str
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "medium": self.medium.value,
            "output": self.output,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class MediumTransducer(Protocol):
    """Protocol for transforming cognitive intent into concrete medium modulation."""

    async def transduce(self, intent: CognitiveIntent) -> TransductionResult:
        """Modulate the medium to express the intent."""
        ...
