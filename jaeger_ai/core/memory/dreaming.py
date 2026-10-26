"""Memory Dreaming — Background memory consolidation for JaegerAI.

Ported from OpenClaw's memory-core dreaming system (simplified).

The dreaming system runs in the background (typically at 3am) and:
1. LIGHT phase: Collects recent memories from episodic store
2. REM phase: Finds recurring patterns and themes
3. DEEP phase: Scores memories and promotes important ones to long-term

Usage:
    from jaeger_ai.core.memory.dreaming import DreamingEngine
    
    engine = DreamingEngine(memory_subsystem)
    await engine.run_dream_cycle()

Or via CLI:
    jaeger memory dream
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from enum import Enum
from datetime import datetime, timezone, timedelta
import asyncio
import json
import logging
import math
import re

logger = logging.getLogger(__name__)


class DreamPhase(str, Enum):
    """The three phases of dreaming."""
    LIGHT = "light"    # Ingest recent memories
    REM = "rem"        # Find patterns
    DEEP = "deep"      # Score and promote


@dataclass
class DreamCandidate:
    """A memory candidate for promotion."""
    content: str
    source: str  # episodic, semantic, working
    timestamp: float
    recall_count: int = 0  # How often recalled
    last_recalled: float = 0.0
    concept_tags: list[str] = field(default_factory=list)
    daily_appearances: int = 0  # Appeared in how many daily sessions
    score: float = 0.0
    promoted: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "source": self.source,
            "recall_count": self.recall_count,
            "score": round(self.score, 3),
            "concept_tags": self.concept_tags,
            "promoted": self.promoted,
        }


@dataclass
class DreamReport:
    """Report from a dreaming cycle."""
    started_at: float
    completed_at: float
    phase: DreamPhase
    candidates_processed: int = 0
    candidates_promoted: int = 0
    patterns_found: list[str] = field(default_factory=list)
    promoted_memories: list[DreamCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    
    @property
    def duration_seconds(self) -> float:
        return self.completed_at - self.started_at
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "candidates_processed": self.candidates_processed,
            "candidates_promoted": self.candidates_promoted,
            "patterns_found": self.patterns_found,
            "promoted": [m.to_dict() for m in self.promoted_memories[:10]],
            "errors": self.errors,
        }


# Scoring weights (from OpenClaw's short-term-promotion.ts)
SCORING_WEIGHTS = {
    "relevance": 0.30,      # Average retrieval quality
    "frequency": 0.24,      # How often recalled
    "diversity": 0.15,      # Distinct user queries
    "recency": 0.15,        # Time-decayed freshness
    "consolidation": 0.10,  # Multi-day recurrence
    "conceptual": 0.06,     # Concept-tag density
}

# Time decay half-life in days
RECENCY_HALF_LIFE_DAYS = 14

# Minimum scores for promotion
MIN_PROMOTION_SCORE = 0.6
MIN_RECALL_COUNT = 2


class DreamingEngine:
    """Background memory consolidation engine.

    Simplified port of OpenClaw's dreaming system, integrated with
    JaegerAI's 5-class memory taxonomy.
    """

    def __init__(
        self,
        memory_subsystem: Any,  # MemorySubsystem from jaeger_ai.core.entity.memory
        state_dir: Path | None = None,
        *,
        lookback_hours: int = 24,
        max_candidates: int = 100,
        promotion_threshold: float = MIN_PROMOTION_SCORE,
    ):
        self.memory = memory_subsystem
        self.state_dir = state_dir or Path.home() / ".jaeger" / "memory" / "dreams"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.lookback_hours = lookback_hours
        self.max_candidates = max_candidates
        self.promotion_threshold = promotion_threshold
        
        # Track recall stats in memory/dreams/recall_stats.json
        self.recall_stats_path = self.state_dir / "recall_stats.json"
        self._recall_stats: dict[str, dict[str, Any]] = self._load_recall_stats()
        
        # Daily dream journal
        self.dreams_journal_path = self.state_dir / "DREAMS.md"

    def _load_recall_stats(self) -> dict[str, dict[str, Any]]:
        """Load recall statistics from disk."""
        if self.recall_stats_path.exists():
            try:
                return json.loads(self.recall_stats_path.read_text())
            except Exception:
                pass
        return {}

    def _save_recall_stats(self) -> None:
        """Save recall statistics to disk."""
        self.recall_stats_path.parent.mkdir(parents=True, exist_ok=True)
        self.recall_stats_path.write_text(json.dumps(self._recall_stats, indent=2))

    def record_recall(self, content_hash: str, query: str) -> None:
        """Record that a memory was recalled via a query.
        
        Call this when the agent retrieves a memory in response to a user query.
        """
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        
        if content_hash not in self._recall_stats:
            self._recall_stats[content_hash] = {
                "recall_count": 0,
                "last_recalled": now.timestamp(),
                "recall_days": [],
                "queries": [],
                "first_recalled": now.timestamp(),
            }
        
        stats = self._recall_stats[content_hash]
        stats["recall_count"] += 1
        stats["last_recalled"] = now.timestamp()
        
        # Track unique days
        if today not in stats["recall_days"]:
            stats["recall_days"].append(today)
        
        # Track unique queries (for diversity score)
        if query not in stats["queries"]:
            stats["queries"].append(query)
        
        self._save_recall_stats()

    # ─────────────────────────────────────────────────────────────
    # LIGHT PHASE: Collect recent memories
    # ─────────────────────────────────────────────────────────────

    async def _light_phase(self, since: datetime) -> list[DreamCandidate]:
        """Collect recent memories from episodic and semantic stores."""
        candidates: list[DreamCandidate] = []
        
        # Get recent episodic events
        try:
            events = await self._get_recent_events(since)
            for event in events:
                # Create candidate from event
                content = self._event_to_memory(event)
                if content and len(content) > 20:  # Skip trivial events
                    candidate = DreamCandidate(
                        content=content,
                        source="episodic",
                        timestamp=event.get("timestamp", 0),
                    )
                    self._enrich_with_recall_stats(candidate)
                    candidates.append(candidate)
        except Exception as e:
            logger.error(f"Failed to collect episodic events: {e}")
        
        # Get recent semantic claims
        try:
            claims = await self._get_recent_claims(since)
            for claim in claims:
                content = self._claim_to_memory(claim)
                if content:
                    candidate = DreamCandidate(
                        content=content,
                        source="semantic",
                        timestamp=claim.get("timestamp", 0),
                    )
                    self._enrich_with_recall_stats(candidate)
                    candidates.append(candidate)
        except Exception as e:
            logger.error(f"Failed to collect semantic claims: {e}")
        
        # Dedupe by content similarity
        candidates = self._dedupe_candidates(candidates)
        
        # Sort by timestamp, keep most recent
        candidates.sort(key=lambda c: c.timestamp, reverse=True)
        return candidates[:self.max_candidates]

    async def _get_recent_events(self, since: datetime) -> list[dict[str, Any]]:
        """Get recent events from episodic memory."""
        # Query the event store for events since timestamp
        cutoff = since.timestamp()
        # This would interface with SqliteEventStore
        events = []
        try:
            if hasattr(self.memory, "episodic_store"):
                store = self.memory.episodic_store
                if hasattr(store, "events_since"):
                    events = store.events_since(cutoff)
        except Exception as e:
            logger.debug(f"Could not query events: {e}")
        return events

    async def _get_recent_claims(self, since: datetime) -> list[dict[str, Any]]:
        """Get recent claims from semantic memory."""
        cutoff = since.timestamp()
        claims = []
        try:
            if hasattr(self.memory, "semantic_store"):
                store = self.memory.semantic_store
                if hasattr(store, "claims_since"):
                    claims = store.claims_since(cutoff)
        except Exception as e:
            logger.debug(f"Could not query claims: {e}")
        return claims

    def _event_to_memory(self, event: dict[str, Any]) -> str:
        """Convert an event to a memory string."""
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})
        
        # Human messages are valuable memories
        if event_type == "human.message":
            return f"User said: {payload.get('text', '')}"
        
        # Tool completions with results
        if event_type == "tool.completed":
            tool = payload.get("tool_name", "unknown")
            result = payload.get("result", "")
            if isinstance(result, str) and len(result) < 500:
                return f"{tool} completed: {result}"
        
        # Learning events
        if event_type == "learning.updated":
            return f"Learned: {payload.get('content', '')}"
        
        return ""

    def _claim_to_memory(self, claim: dict[str, Any]) -> str:
        """Convert a semantic claim to a memory string."""
        statement = claim.get("statement", "")
        confidence = claim.get("confidence", 0.5)
        if statement and confidence > 0.7:
            return f"Known: {statement}"
        return ""

    def _enrich_with_recall_stats(self, candidate: DreamCandidate) -> None:
        """Add recall statistics to a candidate."""
        content_hash = self._hash_content(candidate.content)
        stats = self._recall_stats.get(content_hash)
        if stats:
            candidate.recall_count = stats.get("recall_count", 0)
            candidate.last_recalled = stats.get("last_recalled", 0)
            candidate.daily_appearances = len(stats.get("recall_days", []))

    def _hash_content(self, content: str) -> str:
        """Create a hash of content for tracking."""
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _dedupe_candidates(self, candidates: list[DreamCandidate]) -> list[DreamCandidate]:
        """Remove duplicate candidates based on content similarity."""
        seen: set[str] = set()
        unique: list[DreamCandidate] = []
        
        for candidate in candidates:
            # Normalize content for comparison
            normalized = ' '.join(candidate.content.lower().split())
            # Use prefix matching for similarity (first 50 chars)
            key = normalized[:50]
            # Also check if one content starts with another (substring match)
            is_duplicate = False
            for existing_key in seen:
                # If one starts with the other, consider it a duplicate
                if normalized.startswith(existing_key[:30]) or existing_key.startswith(normalized[:30]):
                    is_duplicate = True
                    break
            if not is_duplicate:
                seen.add(key)
                unique.append(candidate)
        
        return unique

    # ─────────────────────────────────────────────────────────────
    # REM PHASE: Find patterns
    # ─────────────────────────────────────────────────────────────

    async def _rem_phase(self, candidates: list[DreamCandidate]) -> list[str]:
        """Find recurring patterns and themes in candidates."""
        # Extract concept tags from all candidates
        tag_counts: dict[str, int] = {}
        tag_examples: dict[str, list[str]] = {}
        
        for candidate in candidates:
            tags = self._extract_concept_tags(candidate.content)
            candidate.concept_tags = tags
            
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                if tag not in tag_examples:
                    tag_examples[tag] = []
                if len(tag_examples[tag]) < 3:
                    tag_examples[tag].append(candidate.content[:100])
        
        # Find patterns: tags appearing in >30% of candidates
        threshold = max(2, len(candidates) * 0.3)
        patterns = [
            tag for tag, count in tag_counts.items()
            if count >= threshold
        ]
        
        # Sort by frequency
        patterns.sort(key=lambda t: tag_counts[t], reverse=True)
        
        logger.info(f"REM phase found {len(patterns)} patterns: {patterns[:5]}")
        return patterns[:10]  # Top 10 patterns

    def _extract_concept_tags(self, content: str) -> list[str]:
        """Extract concept tags from content using simple keyword matching."""
        # Common concepts to detect
        concept_patterns = {
            "work": r"\b(work|job|office|meeting|deadline|project|client|team)\b",
            "coding": r"\b(code|coding|programming|bug|fix|function|api|debug|debugging|test|tutorial|script|software)\b",
            "learning": r"\b(learn|study|read|research|understand|know|teach)\b",
            "communication": r"\b(email|message|call|talk|discuss|meeting)\b",
            "planning": r"\b(plan|schedule|todo|goal|task|priority)\b",
            "problem": r"\b(problem|issue|error|fail|broken|fix|help|debug|debugging|stuck)\b",
            "decision": r"\b(decide|choice|option|prefer|should)\b",
            "personal": r"\b(family|home|personal|friend|feel|think)\b",
            "technical": r"\b(system|server|database|config|deploy|api)\b",
            "creative": r"\b(create|design|write|build|make|idea)\b",
        }
        
        tags = []
        content_lower = content.lower()
        for tag, pattern in concept_patterns.items():
            if re.search(pattern, content_lower):
                tags.append(tag)
        
        return tags

    # ─────────────────────────────────────────────────────────────
    # DEEP PHASE: Score and promote
    # ─────────────────────────────────────────────────────────────

    async def _deep_phase(
        self,
        candidates: list[DreamCandidate],
        patterns: list[str],
    ) -> list[DreamCandidate]:
        """Score candidates and promote important ones to long-term memory."""
        now = datetime.now(timezone.utc)
        promoted: list[DreamCandidate] = []
        
        for candidate in candidates:
            # Calculate score
            candidate.score = self._calculate_score(candidate, now, patterns)
            
            # Promote if above threshold
            if (
                candidate.score >= self.promotion_threshold
                and candidate.recall_count >= MIN_RECALL_COUNT
                and not candidate.promoted
            ):
                # Promote to semantic memory (long-term)
                await self._promote_to_long_term(candidate)
                candidate.promoted = True
                promoted.append(candidate)
        
        # Sort promoted by score
        promoted.sort(key=lambda c: c.score, reverse=True)
        
        logger.info(f"DEEP phase promoted {len(promoted)} memories")
        return promoted

    def _calculate_score(
        self,
        candidate: DreamCandidate,
        now: datetime,
        patterns: list[str],
    ) -> float:
        """Calculate promotion score for a candidate.
        
        Based on OpenClaw's scoring algorithm with weights:
        - relevance: 0.30 (average quality)
        - frequency: 0.24 (how often recalled)
        - diversity: 0.15 (distinct queries)
        - recency: 0.15 (time-decayed freshness)
        - consolidation: 0.10 (multi-day recurrence)
        - conceptual: 0.06 (concept-tag density)
        """
        # Frequency: log-scaled recall count
        frequency = min(1.0, math.log1p(candidate.recall_count) / math.log1p(10))
        
        # Diversity: unique queries (we track this in recall_stats)
        content_hash = self._hash_content(candidate.content)
        stats = self._recall_stats.get(content_hash, {})
        unique_queries = len(stats.get("queries", []))
        diversity = min(1.0, unique_queries / 5)
        
        # Recency: exponential decay
        if candidate.last_recalled > 0:
            age_days = max(0, (now.timestamp() - candidate.last_recalled) / 86400)
            recency = math.exp(-math.log(2) * age_days / RECENCY_HALF_LIFE_DAYS)
        else:
            # Use creation time for never-recalled memories
            age_days = max(0, (now.timestamp() - candidate.timestamp) / 86400)
            recency = math.exp(-math.log(2) * age_days / RECENCY_HALF_LIFE_DAYS) * 0.5
        
        # Consolidation: multi-day recurrence
        consolidation = min(1.0, candidate.daily_appearances / 3)
        
        # Conceptual: tag density + pattern match bonus
        conceptual = min(1.0, len(candidate.concept_tags) / 6)
        pattern_bonus = 0.1 if any(tag in patterns for tag in candidate.concept_tags) else 0
        
        # Relevance: base quality score (content length + source)
        relevance = self._calculate_relevance(candidate)
        
        # Weighted sum
        score = (
            SCORING_WEIGHTS["relevance"] * relevance +
            SCORING_WEIGHTS["frequency"] * frequency +
            SCORING_WEIGHTS["diversity"] * diversity +
            SCORING_WEIGHTS["recency"] * recency +
            SCORING_WEIGHTS["consolidation"] * consolidation +
            SCORING_WEIGHTS["conceptual"] * conceptual +
            pattern_bonus
        )
        
        return min(1.0, score)

    def _calculate_relevance(self, candidate: DreamCandidate) -> float:
        """Calculate base relevance score."""
        # Longer content = more detailed = more relevant
        length_score = min(1.0, len(candidate.content) / 500)
        
        # Episodic memories from user interactions are more relevant
        source_score = 1.0 if candidate.source == "episodic" else 0.8
        
        return (length_score * 0.4 + source_score * 0.6)

    async def _promote_to_long_term(self, candidate: DreamCandidate) -> None:
        """Promote a candidate to long-term semantic memory."""
        try:
            if hasattr(self.memory, "semantic_store"):
                store = self.memory.semantic_store
                if hasattr(store, "add_claim"):
                    claim = {
                        "statement": candidate.content,
                        "confidence": 0.8,
                        "source": f"dreaming:{candidate.source}",
                        "tags": candidate.concept_tags,
                        "promoted_from": "dreaming",
                        "original_timestamp": candidate.timestamp,
                    }
                    store.add_claim(claim)
                    logger.debug(f"Promoted to semantic memory: {candidate.content[:100]}...")
        except Exception as e:
            logger.error(f"Failed to promote candidate: {e}")

    # ─────────────────────────────────────────────────────────────
    # Main Entry Point
    # ─────────────────────────────────────────────────────────────

    async def run_dream_cycle(self, since_hours: int | None = None) -> DreamReport:
        """Run a complete dreaming cycle.
        
        Args:
            since_hours: How far back to look for memories (default: self.lookback_hours)
            
        Returns:
            DreamReport with results
        """
        started_at = datetime.now(timezone.utc).timestamp()
        since_hours = since_hours or self.lookback_hours
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        
        logger.info(f"Starting dream cycle (looking back {since_hours}h)")
        
        # Run all three phases
        candidates = await self._light_phase(since)
        patterns = await self._rem_phase(candidates)
        promoted = await self._deep_phase(candidates, patterns)
        
        completed_at = datetime.now(timezone.utc).timestamp()
        
        report = DreamReport(
            started_at=started_at,
            completed_at=completed_at,
            phase=DreamPhase.DEEP,  # Final phase
            candidates_processed=len(candidates),
            candidates_promoted=len(promoted),
            patterns_found=patterns,
            promoted_memories=promoted,
        )
        
        # Write dream journal entry
        await self._write_dream_journal(report)
        
        logger.info(
            f"Dream cycle complete: {len(candidates)} candidates, "
            f"{len(promoted)} promoted, {len(patterns)} patterns"
        )
        
        return report

    async def _write_dream_journal(self, report: DreamReport) -> None:
        """Write a dream journal entry to DREAMS.md."""
        today = datetime.now(timezone.utc).date().isoformat()
        
        entry = f"""
## Dream Cycle: {datetime.now(timezone.utc).isoformat()}

- **Duration:** {report.duration_seconds:.1f}s
- **Candidates processed:** {report.candidates_processed}
- **Memories promoted:** {report.candidates_promoted}
- **Patterns found:** {', '.join(report.patterns_found[:5]) if report.patterns_found else 'none'}

### Promoted Memories
"""
        
        for memory in report.promoted_memories[:5]:
            entry += f"- [{memory.score:.2f}] {memory.content[:150]}...\n"
        
        if len(report.promoted_memories) > 5:
            entry += f"- ... and {len(report.promoted_memories) - 5} more\n"
        
        entry += "\n---\n"
        
        # Append to journal
        with open(self.dreams_journal_path, "a") as f:
            f.write(entry)

    def schedule_dreaming(self, hour: int = 3, minute: int = 0) -> None:
        """Schedule daily dreaming at a specific time.
        
        This would integrate with the UnifiedScheduler.
        """
        # TODO: Integrate with UnifiedScheduler
        # For now, this can be called manually or via cron
        pass


# ─────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────

async def run_dreaming(memory_subsystem: Any, **kwargs) -> DreamReport:
    """Run a single dreaming cycle.
    
    Convenience function for CLI usage.
    """
    engine = DreamingEngine(memory_subsystem, **kwargs)
    return await engine.run_dream_cycle()


def get_dreaming_status(state_dir: Path | None = None) -> dict[str, Any]:
    """Get the status of the dreaming system."""
    state_dir = state_dir or Path.home() / ".jaeger" / "memory" / "dreams"
    
    stats_path = state_dir / "recall_stats.json"
    journal_path = state_dir / "DREAMS.md"
    
    status = {
        "enabled": True,
        "state_dir": str(state_dir),
        "tracked_memories": 0,
        "total_dream_cycles": 0,
        "last_dream_cycle": None,
    }
    
    if stats_path.exists():
        try:
            stats = json.loads(stats_path.read_text())
            status["tracked_memories"] = len(stats)
        except Exception:
            pass
    
    if journal_path.exists():
        content = journal_path.read_text()
        # Count dream cycle entries
        status["total_dream_cycles"] = content.count("## Dream Cycle:")
        # Find last cycle date
        lines = content.split("\n")
        for line in reversed(lines):
            if line.startswith("## Dream Cycle:"):
                status["last_dream_cycle"] = line.replace("## Dream Cycle:", "").strip()
                break
    
    return status


__all__ = [
    "DreamingEngine",
    "DreamPhase",
    "DreamCandidate",
    "DreamReport",
    "run_dreaming",
    "get_dreaming_status",
    "SCORING_WEIGHTS",
]
