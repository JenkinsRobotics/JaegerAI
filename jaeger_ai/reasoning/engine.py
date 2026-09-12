"""Central Reasoning Engine orchestrating perception, intent, transduction, and learning.

Experimental endogenous heartbeat cognition — not an AGI/SI replacement.
Dangerous system actions and desktop notifications are fail-closed unless
explicitly allowed on ``ReasoningConfig``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .belief import EpistemicContext
from .intent import CognitiveIntent, IntentEngine, MediumType
from .learning import EpistemicLearningLoop
from .perception import PerceptionSnapshot, SensorStream
from .transducers import (
    AcousticTransducer,
    SystemTransducer,
    TransducerRegistry,
    TransductionResult,
    VisualTransducer,
)

logger = logging.getLogger(__name__)


@dataclass
class ReasoningConfig:
    """Runtime gates for the experimental cognition loop.

    Defaults are fail-closed for anything that can modify code, run suites,
    or spam notifications.
    """

    enabled: bool = True
    tick_interval_seconds: float = 30.0
    salience_threshold: float = 0.5
    workspace_root: Path | None = None
    data_dir: Path | None = None
    # Explicit allow flags (default False — production harden)
    allow_dangerous_system_actions: bool = False
    allow_notifications: bool = False
    allow_audio_play: bool = False


@dataclass
class ReasoningResult:
    timestamp: float = field(default_factory=time.time)
    status: str = "idle"  # "acted", "vigilant_idle", "disabled", "error"
    snapshot: PerceptionSnapshot | None = None
    intent: CognitiveIntent | None = None
    transductions: list[TransductionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "intent": self.intent.to_dict() if self.intent else None,
            "transductions": [t.to_dict() for t in self.transductions],
        }


class ReasoningEngine:
    """Experimental heartbeat cognition — reasons unprompted, on its own tick.

    Self-contained within JaegerAI. Executes the continuous OODA loop:
    Perception -> Episodic Context -> Endogenous Intent -> Medium Transduction -> Learning.
    """

    def __init__(self, config: ReasoningConfig | None = None) -> None:
        self.config = config or ReasoningConfig()
        root = self.config.workspace_root or Path(os.getcwd())
        default_base = (
            os.environ.get("JAEGER_STATE_DIR")
            or os.environ.get("JAEGER_HOME")
            or os.path.expanduser("~/.jaeger")
        )
        data_dir = self.config.data_dir or (Path(default_base) / "ares")

        self.sensor_stream = SensorStream(workspace_root=root)
        self.epistemic_context = EpistemicContext(cache_dir=data_dir)
        self.intent_engine = IntentEngine(salience_threshold=self.config.salience_threshold)
        self.transducers = TransducerRegistry()
        self.transducers.register(
            MediumType.SYSTEM,
            SystemTransducer(
                workspace_root=root,
                allow_dangerous_actions=self.config.allow_dangerous_system_actions,
            ),
        )
        self.transducers.register(
            MediumType.VISUAL,
            VisualTransducer(
                events_dir=data_dir,
                allow_notifications=self.config.allow_notifications,
            ),
        )
        self.transducers.register(
            MediumType.ACOUSTIC,
            AcousticTransducer(
                enable_audio_play=self.config.allow_audio_play,
                allow_notifications=self.config.allow_notifications,
            ),
        )
        self.learning_loop = EpistemicLearningLoop(context=self.epistemic_context, log_dir=data_dir)

        self._last_tick_ts = 0.0
        self._last_result: ReasoningResult | None = None

    @property
    def last_result(self) -> ReasoningResult | None:
        return self._last_result

    def status(self) -> dict[str, Any]:
        """Provides high-level cognitive telemetry for bridge, UI, and MCP clients."""
        return {
            "enabled": self.config.enabled,
            "experimental": True,
            "not_agi": True,
            "allow_dangerous_system_actions": self.config.allow_dangerous_system_actions,
            "allow_notifications": self.config.allow_notifications,
            "last_tick": self._last_tick_ts,
            "last_status": self._last_result.status if self._last_result else "uninitialized",
            "active_intent": (
                self._last_result.intent.to_dict()
                if self._last_result and self._last_result.intent
                else None
            ),
            "belief": self.epistemic_context.current.to_dict(),
        }

    async def tick(self) -> ReasoningResult:
        """Executes one full autonomous cognitive cycle (never raises to caller)."""
        if not self.config.enabled:
            res = ReasoningResult(status="disabled")
            self._last_result = res
            return res

        self._last_tick_ts = time.time()
        try:
            snapshot = await self.sensor_stream.perceive()
            belief = await self.epistemic_context.orient(snapshot)
            intent = await self.intent_engine.form_intent(snapshot, belief)

            if not intent.is_active:
                res = ReasoningResult(
                    status="vigilant_idle",
                    snapshot=snapshot,
                    intent=intent,
                    transductions=[],
                )
                self._last_result = res
                return res

            transductions = await self.transducers.broadcast(intent)
            await self.learning_loop.record_outcome(intent, transductions)

            res = ReasoningResult(
                status="acted",
                snapshot=snapshot,
                intent=intent,
                transductions=transductions,
            )
            self._last_result = res
            return res

        except Exception as exc:  # noqa: BLE001 — tick must never crash heartbeat
            logger.exception("reasoning tick encountered an error: %s", type(exc).__name__)
            res = ReasoningResult(status=f"error: {type(exc).__name__}")
            self._last_result = res
            return res
