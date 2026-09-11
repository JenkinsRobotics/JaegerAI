"""Central ARES Engine orchestrating perception, reasoning, transduction, and learning."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .belief import BeliefState, EpistemicContext
from .intent import CognitiveIntent, IntentEngine
from .learning import EpistemicLearningLoop
from .perception import PerceptionSnapshot, SensorStream
from .transducers import TransducerRegistry, TransductionResult

logger = logging.getLogger(__name__)


@dataclass
class ARESConfig:
    enabled: bool = True
    tick_interval_seconds: float = 30.0
    salience_threshold: float = 0.5
    workspace_root: Path | None = None
    data_dir: Path | None = None


@dataclass
class ARESResult:
    timestamp: float = field(default_factory=time.time)
    status: str = "idle" # "acted", "vigilant_idle", "disabled", "error"
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


class ARESEngine:
    """Autonomous Reasoning and Execution System.

    Self-contained within JaegerAI. Executes the continuous OODA loop:
    Perception -> Episodic Context -> Endogenous Intent -> Medium Transduction -> Learning.
    """

    def __init__(self, config: ARESConfig | None = None) -> None:
        self.config = config or ARESConfig()
        root = self.config.workspace_root or Path(os.getcwd())
        default_base = os.environ.get("JAEGER_HOME") or os.path.expanduser("~/.jaeger")
        data_dir = self.config.data_dir or (Path(default_base) / "ares")

        self.sensor_stream = SensorStream(workspace_root=root)
        self.epistemic_context = EpistemicContext(cache_dir=data_dir)
        self.intent_engine = IntentEngine(salience_threshold=self.config.salience_threshold)
        self.transducers = TransducerRegistry()
        self.learning_loop = EpistemicLearningLoop(context=self.epistemic_context, log_dir=data_dir)

        self._last_tick_ts = 0.0
        self._last_result: ARESResult | None = None

    @property
    def last_result(self) -> ARESResult | None:
        return self._last_result

    def status(self) -> dict[str, Any]:
        """Provides high-level cognitive telemetry for bridge, UI, and MCP clients."""
        return {
            "enabled": self.config.enabled,
            "last_tick": self._last_tick_ts,
            "last_status": self._last_result.status if self._last_result else "uninitialized",
            "active_intent": self._last_result.intent.to_dict() if self._last_result and self._last_result.intent else None,
            "belief": self.epistemic_context.current.to_dict(),
        }

    async def tick(self) -> ARESResult:
        """Executes one full autonomous cognitive cycle."""
        if not self.config.enabled:
            res = ARESResult(status="disabled")
            self._last_result = res
            return res

        self._last_tick_ts = time.time()
        try:
            # 1. Continuous Observe (Perception)
            snapshot = await self.sensor_stream.perceive()

            # 2. Orient (Epistemic Context & Memory)
            belief = await self.epistemic_context.orient(snapshot)

            # 3. Decide (Endogenous Intent Formation)
            intent = await self.intent_engine.form_intent(snapshot, belief)

            # If below activation threshold, remain in vigilant idle
            if not intent.is_active:
                res = ARESResult(
                    status="vigilant_idle",
                    snapshot=snapshot,
                    intent=intent,
                    transductions=[],
                )
                self._last_result = res
                return res

            # 4. Act (Transduce to Medium)
            transductions = await self.transducers.broadcast(intent)

            # 5. Learn (Epistemic Feedback Loop)
            await self.learning_loop.record_outcome(intent, transductions)

            res = ARESResult(
                status="acted",
                snapshot=snapshot,
                intent=intent,
                transductions=transductions,
            )
            self._last_result = res
            return res

        except Exception as exc:
            logger.exception("ARES cognitive tick encountered an error: %s", exc)
            res = ARESResult(status=f"error: {exc}")
            self._last_result = res
            return res
