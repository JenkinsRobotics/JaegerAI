"""Memory Taxonomy Subsystem (UPAA Principle 8).

Implements explicit, separate implementation ownership for the 5 memory classes:
1. Working Memory: Active turn context, goals, attention focus, transient scratchpad.
2. Episodic / Autobiographical Memory: Chronological, immutable history of all experienced events.
3. Semantic Memory: Structured entities, claims, relationships, and world model facts.
4. Reflective Memory: Synthesized insights, meta-cognitive lessons, evaluated self-critiques.
5. Procedural Memory: Verified skills, executable tool workflows, operational recipes.

ARCHITECTURAL BOUNDARY NOTE:
    SessionStore (jaeger_ai/core/gateway/session_store.py) is strictly a
    TRANSPORT/SESSION CACHE for multi-client gateway connections (SSE/REST
    bookkeeping and turn buffering). It is NOT the entity's memory system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping, Sequence

from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .self_state import SelfState

logger = logging.getLogger("jaeger.entity.memory")


class MemoryKind(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    REFLECTIVE = "reflective"
    PROCEDURAL = "procedural"


# ── 1. Working Memory ──────────────────────────────────────────────────

@dataclass
class WorkingMemory:
    """Transient, in-memory workspace representing the active context.
    
    Canonical Store: In-memory working buffer + SelfState projection.
    Write Path: Updated per turn / per event by deterministic reduction.
    Retrieval Interface: `get_active_context()`, `get_active_goals()`.
    Persistence: Transient / reconstructed on cold boot from episodic log.
    """

    scratchpad: dict[str, Any] = field(default_factory=dict)
    active_goals: list[str] = field(default_factory=list)
    current_focus: str = "idle"
    recent_events_window: list[JaegerEvent] = field(default_factory=list)
    max_window_size: int = 20

    def update_from_state(self, state: SelfState) -> None:
        self.active_goals = list(state.active_goals)
        self.current_focus = state.current_focus

    def record_turn_event(self, event: JaegerEvent) -> None:
        self.recent_events_window.append(event)
        if len(self.recent_events_window) > self.max_window_size:
            self.recent_events_window.pop(0)

    def set_scratch(self, key: str, value: Any) -> None:
        self.scratchpad[key] = value

    def get_scratch(self, key: str, default: Any = None) -> Any:
        return self.scratchpad.get(key, default)


# ── 2. Episodic / Autobiographical Memory ──────────────────────────────

class EpisodicMemory:
    """Chronological, immutable experiential history of the entity.
    
    Canonical Store: SqliteEventStore (<state_root>/entity_events.sqlite3).
    Write Path: `record_event(event)` -> append-only SQLite WAL write.
    Retrieval Interface: `query(actor, session_id, limit)`, `replay_all()`.
    Persistence: Durable, permanent, indexed SQLite database.
    """

    def __init__(self, event_store: SqliteEventStore) -> None:
        self.store = event_store

    def record_event(self, event: JaegerEvent) -> JaegerEvent:
        return self.store.append(event)

    def query_history(
        self,
        *,
        session_id: str | None = None,
        event_type: str | None = None,
        actor: str | None = None,
        limit: int = 50,
    ) -> Sequence[JaegerEvent]:
        return self.store.query_events(
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            limit=limit,
        )

    def replay(self) -> Sequence[JaegerEvent]:
        return list(self.store.replay_all())

    def record_interaction(
        self,
        session_id: str,
        user_text: str,
        agent_response: str,
        tool_calls: list[Any] | None = None,
    ) -> None:
        event = JaegerEvent(
            event_id=f"epi-{int(time.time()*1000)}",
            event_type=EventType.AGENT_RESPONSE.value,
            actor="agent:jaeger",
            source="memory.episodic",
            timestamp=time.time(),
            session_id=session_id,
            payload={
                "user_text": user_text,
                "agent_response": agent_response,
                "tool_calls": tool_calls or [],
            },
            salience=0.5,
        )
        self.store.append(event)

    def get_session_episodes(self, session_id: str) -> list[EpisodeSummary]:
        events = self.store.query_events(session_id=session_id, limit=100)
        episodes = []
        for e in events:
            if isinstance(e.payload, dict) and "user_text" in e.payload and "agent_response" in e.payload:
                episodes.append(EpisodeSummary(
                    session_id=session_id,
                    user_text=str(e.payload.get("user_text") or ""),
                    agent_response=str(e.payload.get("agent_response") or ""),
                    tool_calls=list(e.payload.get("tool_calls") or []),
                    timestamp=e.timestamp,
                ))
        return episodes


@dataclass(frozen=True)
class EpisodeSummary:
    session_id: str
    user_text: str
    agent_response: str
    tool_calls: list[Any] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


# ── 3. Semantic Memory ─────────────────────────────────────────────────

class SemanticMemory:
    """Structured knowledge, entities, claims, and verified world facts.
    
    Canonical Store: WorldModel & SqliteKnowledgeStore (<state_root>/knowledge.sqlite3).
    Write Path: Extracted during consolidation or turn intake -> `record_claim()`.
    Retrieval Interface: `query_claims()`, `get_entity_facts()`.
    Persistence: Durable relational SQLite entity/claim tables.
    """

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self._db_path = state_root / "knowledge.sqlite3"
        self._init_db()

    def _init_db(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source_id TEXT,
                    confidence REAL,
                    created_at REAL
                )
                """
            )
            conn.commit()

    def record_claim(
        self,
        subject: str,
        predicate: str,
        value: str,
        *,
        source_id: str = "",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Record a verified factual proposition about an entity."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO semantic_claims (subject, predicate, value, source_id, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (subject, predicate, value, source_id, confidence, time.time()),
            )
            conn.commit()
        return {"subject": subject, "predicate": predicate, "value": value, "status": "recorded"}

    def query_claims(self, subject: str) -> list[dict[str, Any]]:
        """Retrieve established semantic claims for a given subject."""
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "SELECT predicate, value, confidence FROM semantic_claims WHERE subject = ?",
                (subject,),
            )
            return [
                {"predicate": r[0], "value": r[1], "confidence": r[2]}
                for r in cur.fetchall()
            ]


# ── 4. Reflective Memory ───────────────────────────────────────────────

@dataclass
class ReflectiveInsight:
    insight_id: str
    topic: str
    observation: str
    implication: str
    created_at: float = field(default_factory=time.time)


class ReflectiveMemory:
    """Distilled meta-cognitive lessons, evaluations, and synthesized principles.
    
    Canonical Store: ReflectiveStore (<state_root>/reflective_insights.json).
    Write Path: Sleep-time consolidation / post-turn reflection -> `store_insight()`.
    Retrieval Interface: `get_recent_insights(limit)`, `query_by_topic(topic)`.
    Persistence: Durable JSON/SQLite storage, injected into SelfState.recent_insights.
    """

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self._store_file = state_root / "reflective_insights.json"
        self._insights: list[ReflectiveInsight] = self._load()

    def _load(self) -> list[ReflectiveInsight]:
        if not self._store_file.exists():
            return []
        try:
            data = json.loads(self._store_file.read_text(encoding="utf-8"))
            return [ReflectiveInsight(**item) for item in data]
        except Exception as exc:
            logger.warning("Failed loading reflective insights: %s", exc)
            return []

    def _save(self) -> None:
        try:
            raw = [
                {
                    "insight_id": ins.insight_id,
                    "topic": ins.topic,
                    "observation": ins.observation,
                    "implication": ins.implication,
                    "created_at": ins.created_at,
                }
                for ins in self._insights
            ]
            self._store_file.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed saving reflective insights: %s", exc)

    def store_insight(self, topic: str, observation: str, implication: str) -> ReflectiveInsight:
        ins = ReflectiveInsight(
            insight_id=f"ins-{int(time.time()*1000)}",
            topic=topic,
            observation=observation,
            implication=implication,
        )
        self._insights.append(ins)
        self._save()
        return ins

    def get_recent_insights(self, limit: int = 10) -> list[ReflectiveInsight]:
        return list(reversed(self._insights[-limit:]))


# ── 5. Procedural Memory ───────────────────────────────────────────────

class ProceduralMemory:
    """Verified skills, executable recipes, and validated operational procedures.
    
    Canonical Store: Skill Library directory (<state_root>/skills/ or repo skills).
    Write Path: Voyager skill promotion pipeline -> verified Python/Markdown manifests.
    Retrieval Interface: `list_skills()`, `get_skill(name)`, `search_skills(query)`.
    Persistence: File-based verified code manifests with automated assertions.
    """

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.skill_dir = state_root / "skills"
        self.skill_dir.mkdir(parents=True, exist_ok=True)

    def list_skills(self) -> list[str]:
        return [p.stem for p in self.skill_dir.glob("*.py")] + [p.stem for p in self.skill_dir.glob("*.md")]

    def get_skill(self, name: str) -> str | None:
        for ext in (".py", ".md", ".json"):
            path = self.skill_dir / f"{name}{ext}"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None


# ── Unified Memory Subsystem ──────────────────────────────────────────

class MemorySubsystem:
    """Unified access layer coordinating the 5 canonical memory classes."""

    def __init__(self, state_root: Path, event_store: SqliteEventStore) -> None:
        self.state_root = state_root
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory(event_store)
        self.semantic = SemanticMemory(state_root)
        self.reflective = ReflectiveMemory(state_root)
        self.procedural = ProceduralMemory(state_root)

    def summarize_telemetry(self) -> dict[str, Any]:
        return {
            "working_goals_count": len(self.working.active_goals),
            "working_scratchpad_keys": list(self.working.scratchpad.keys()),
            "episodic_event_count": len(self.episodic.replay()),
            "reflective_insights_count": len(self.reflective._insights),
            "procedural_skills_count": len(self.procedural.list_skills()),
        }
