"""Memory Consolidation and Between-Turn Reflection ("Dreaming") for Jaeger.

Adopts the Generative Agents reflection loop and Letta's sleep-time architecture:
- Examines recent episodic events from the persistent event log.
- Extracts declarative assertions and relationships into Jaeger's canonical WorldModel.
- Synthesizes higher-order insights and summaries with clear provenance.
- Emits `memory.consolidated` events into the event log and updates SelfState.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from .events import EventType, JaegerEvent
from .self_state import SelfState

logger = logging.getLogger("jaeger.entity.consolidation")


class MemoryConsolidator:
    """Performs offline / idle memory consolidation and reflection."""

    def __init__(self, world_model: Any = None) -> None:
        self._world_model = world_model

    def _get_world_model(self) -> Any:
        if self._world_model is not None:
            return self._world_model
        try:
            from jaeger_agent.cognition.world import WorldModel
            from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore
            self._world_model = WorldModel(SqliteKnowledgeStore())
            return self._world_model
        except Exception as exc:
            logger.debug("WorldModel unavailable for consolidation: %s", exc)
            return None

    def consolidate(
        self,
        events: Sequence[JaegerEvent],
        current_state: SelfState,
    ) -> list[str]:
        """Process un-consolidated episodic events, admitting them to the world model

        and extracting high-level insights. Returns a list of new insights.
        """
        new_insights: list[str] = []
        wm = self._get_world_model()

        for evt in events:
            # 1. Ingest conversational and observation text into WorldModel
            if evt.event_type == EventType.HUMAN_MESSAGE.value:
                text = str(evt.payload.get("text") or "").strip()
                if text and wm is not None:
                    try:
                        from jaeger_agent.cognition.world import WorldEvent
                        world_evt = WorldEvent.for_session(text, evt.session_id)
                        wm.ingest(world_evt)
                    except Exception as exc:
                        logger.debug("Failed to ingest WorldEvent for msg %s: %s", evt.event_id, exc)

            # 2. Extract tool consequence patterns
            elif evt.event_type == EventType.TOOL_COMPLETED.value:
                tool = evt.payload.get("tool")
                dur = evt.payload.get("duration_s", 0)
                if tool and dur > 10.0:
                    new_insights.append(f"Tool {tool} completed with noticeable duration ({dur:.1f}s)")

            # 3. Environmental observation telemetry patterns
            elif evt.event_type == EventType.PERCEPTION_SENSED.value:
                dirty = evt.payload.get("dirty_files")
                if dirty and int(dirty) > 10:
                    new_insights.append(f"Repository dirty file count elevated ({dirty} files)")

        return new_insights
