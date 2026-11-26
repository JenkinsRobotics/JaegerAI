"""Asynchronous, event-driven 24/7 Cognitive Life Loop independent of user chat.

Architecture invariant:
  *Conversation is an interface to the intelligence, not its execution loop.*

Each cognitive tick (or incoming perception wake):
1. Updates temporal awareness (`time_of_day`, `uptime_s`, `idle_s`, `mode`) in `WorldModelStore`.
2. Evaluates pending high-salience perceptions (mic, camera, channels, embodiment sensors).
3. Consults `ResourceGovernor` (32 GB budget + 3-tier Owner-First Priority):
   - If Owner Work is active -> stays in `serving_owner` (yields all heavy compute).
   - If proactive Business/Scheduled work is due -> executes registered proactive handler.
   - If idle & allowed -> executes registered Idle Life handler (e.g. headless Minecraft persistence).
4. Emits live cognitive state updates (mood, activity, focus, avatar emotion) so UI,
   VR Avatar, Voice, and Chat interfaces can observe and steer the living mind in real time.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Mapping

from .world_model import PerceptionEvent, WorldModelStore

ProactiveHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None] | dict[str, Any] | None]


@dataclass
class CognitiveState:
    mode: str = "observing"  # "serving_owner" | "proactive_work" | "idle_life" | "observing" | "estop"
    emotion: str = "calm"  # maps cleanly to VRM/2D avatar expressions
    focus: str = "Standing by"
    tick_count: int = 0
    started_at: float = field(default_factory=time.time)
    last_tick_at: float = 0.0
    last_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "emotion": self.emotion,
            "focus": self.focus,
            "tick_count": self.tick_count,
            "uptime_s": round(time.time() - self.started_at, 1),
            "last_tick_at": self.last_tick_at,
            "last_action": self.last_action,
        }


def _time_of_day_bucket(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


class CognitiveLifeLoop:
    """Persistent, event-driven background mind loop running independently of chat turns."""

    def __init__(
        self,
        *,
        world: WorldModelStore,
        governor: Any = None,
        tick_interval_s: float = 15.0,
        on_state_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._world = world
        self._governor = governor
        self._tick_interval_s = max(0.05, float(tick_interval_s))
        self._on_state_change = on_state_change
        self._state = CognitiveState()
        self._proactive_handlers: dict[str, ProactiveHandler] = {}
        self._idle_handlers: dict[str, ProactiveHandler] = {}
        self._perception_queue: asyncio.Queue[PerceptionEvent] | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def state(self) -> CognitiveState:
        return self._state

    def register_proactive_handler(self, name: str, fn: ProactiveHandler) -> None:
        self._proactive_handlers[name] = fn

    def register_idle_life_handler(self, name: str, fn: ProactiveHandler) -> None:
        self._idle_handlers[name] = fn

    def ingest_perception(
        self,
        *,
        modality: str,
        kind: str,
        payload: Mapping[str, Any],
        salience: float = 0.5,
    ) -> PerceptionEvent:
        """Record a multimodal perception into the world model and wake the cognitive loop."""
        ev = self._world.record_perception(
            modality=modality,
            kind=kind,
            payload=payload,
            salience=salience,
        )
        self._world.observe(domain="perception", key=f"last_{modality}", value={"kind": kind, **dict(payload)}, source=modality)
        if self._perception_queue is not None:
            try:
                self._perception_queue.put_nowait(ev)
            except asyncio.QueueFull:
                pass
        return ev

    async def _invoke_handler(self, fn: ProactiveHandler, ctx: dict[str, Any]) -> dict[str, Any] | None:
        res = fn(ctx)
        if asyncio.iscoroutine(res) or isinstance(res, Awaitable):
            res = await res  # type: ignore[misc]
        return dict(res) if isinstance(res, Mapping) else None

    async def step_once(self, *, trigger: str = "temporal_tick") -> CognitiveState:
        """Execute one deterministic cognitive perception-reason-act cycle."""
        now = time.time()
        dt = datetime.now()
        self._state.tick_count += 1
        self._state.last_tick_at = now

        # 1. Update temporal awareness in the persistent world model
        self._world.observe(
            domain="temporal",
            key="clock",
            value={
                "local_iso": dt.isoformat(timespec="seconds"),
                "hour": dt.hour,
                "bucket": _time_of_day_bucket(dt.hour),
                "tick": self._state.tick_count,
                "trigger": trigger,
            },
            source="temporal_clock",
        )

        # 2. Check 32 GB ResourceGovernor + 3-tier Owner-First priority
        gov_snap = self._governor.snapshot() if self._governor is not None else {}
        if gov_snap.get("estop_active"):
            self._state.mode = "estop"
            self._state.emotion = "concerned"
            self._state.focus = "Emergency Stop latched"
        elif int(gov_snap.get("active_owner_runs") or 0) > 0:
            self._state.mode = "serving_owner"
            self._state.emotion = "focused"
            self._state.focus = "Working on owner request"
        else:
            # 3. Try proactive goal-directed business/scheduled work first
            ran_proactive = False
            ctx = {
                "world": self._world.snapshot(),
                "resources": gov_snap,
                "trigger": trigger,
                "tick": self._state.tick_count,
            }
            for name, fn in list(self._proactive_handlers.items()):
                try:
                    outcome = await self._invoke_handler(fn, ctx)
                    if outcome and outcome.get("acted"):
                        ran_proactive = True
                        self._state.mode = "proactive_work"
                        self._state.emotion = str(outcome.get("emotion") or "focused")
                        self._state.focus = str(outcome.get("focus") or f"Proactive: {name}")
                        self._state.last_action = f"{name}:{outcome.get('summary') or 'acted'}"
                        break
                except Exception as exc:  # noqa: BLE001
                    self._world.observe(domain="system", key=f"handler_error:{name}", value=str(exc), source=name)

            # 4. Otherwise, if Tier 3 Idle Life is allowed, run persistent idle autonomy (e.g. Minecraft)
            if not ran_proactive:
                idle_allowed = bool(gov_snap.get("idle_life_allowed_now", True))
                ran_idle = False
                if idle_allowed and self._idle_handlers:
                    for name, fn in list(self._idle_handlers.items()):
                        try:
                            outcome = await self._invoke_handler(fn, ctx)
                            if outcome and outcome.get("acted"):
                                ran_idle = True
                                self._state.mode = "idle_life"
                                self._state.emotion = str(outcome.get("emotion") or "happy")
                                self._state.focus = str(outcome.get("focus") or f"Idle life: {name}")
                                self._state.last_action = f"{name}:{outcome.get('summary') or 'stepped'}"
                                break
                        except Exception as exc:  # noqa: BLE001
                            self._world.observe(domain="system", key=f"idle_error:{name}", value=str(exc), source=name)
                if not ran_idle:
                    self._state.mode = "observing"
                    self._state.emotion = "warm"
                    self._state.focus = f"Aware & standing by ({_time_of_day_bucket(dt.hour)})"

        self._world.observe(domain="system", key="cognitive_state", value=self._state.to_dict(), source="cognition")
        if self._on_state_change is not None:
            try:
                self._on_state_change(self._state.to_dict())
            except Exception:  # noqa: BLE001
                pass
        return self._state

    async def _run_forever(self) -> None:
        self._perception_queue = asyncio.Queue(maxsize=256)
        while self._running:
            trigger = "temporal_tick"
            try:
                ev = await asyncio.wait_for(self._perception_queue.get(), timeout=self._tick_interval_s)
                trigger = f"perception:{ev.modality}:{ev.kind}"
            except asyncio.TimeoutError:
                pass
            if not self._running:
                break
            await self.step_once(trigger=trigger)

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._running = True
        self._task = asyncio.create_task(self._run_forever(), name="jaeger-cognitive-life-loop")
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


__all__ = ["CognitiveLifeLoop", "CognitiveState", "ProactiveHandler"]
