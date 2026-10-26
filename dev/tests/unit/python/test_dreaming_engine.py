"""Unit tests for the Dreaming Engine (memory consolidation)."""

from __future__ import annotations

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

from jaeger_ai.core.memory.dreaming import (
    DreamingEngine,
    DreamCandidate,
    DreamPhase,
    DreamReport,
    SCORING_WEIGHTS,
    get_dreaming_status,
)


class TestDreamCandidate:
    """Test DreamCandidate dataclass."""
    
    def test_basic_candidate(self):
        candidate = DreamCandidate(
            content="User likes Python programming",
            source="episodic",
            timestamp=1234567890.0,
        )
        assert candidate.content == "User likes Python programming"
        assert candidate.source == "episodic"
        assert candidate.recall_count == 0
        assert candidate.score == 0.0
        assert not candidate.promoted
    
    def test_candidate_to_dict(self):
        candidate = DreamCandidate(
            content="A" * 300,  # Long content
            source="semantic",
            timestamp=1234567890.0,
            recall_count=5,
            score=0.85,
            concept_tags=["coding", "python"],
        )
        result = candidate.to_dict()
        
        assert result["source"] == "semantic"
        assert result["recall_count"] == 5
        assert result["score"] == 0.85
        assert result["concept_tags"] == ["coding", "python"]
        assert len(result["content"]) < 300  # Truncated
        assert result["content"].endswith("...")


class TestDreamReport:
    """Test DreamReport dataclass."""
    
    def test_basic_report(self):
        report = DreamReport(
            started_at=1000.0,
            completed_at=1005.5,
            phase=DreamPhase.DEEP,
            candidates_processed=10,
            candidates_promoted=3,
            patterns_found=["coding", "python"],
        )
        
        assert report.duration_seconds == 5.5
        assert report.candidates_processed == 10
        assert report.candidates_promoted == 3
    
    def test_report_to_dict(self):
        report = DreamReport(
            started_at=1000.0,
            completed_at=1005.5,
            phase=DreamPhase.LIGHT,
        )
        result = report.to_dict()
        
        assert result["duration_seconds"] == 5.5
        assert result["candidates_processed"] == 0
        assert isinstance(result["promoted"], list)


class TestDreamingEngine:
    """Test DreamingEngine."""
    
    @pytest.fixture
    def temp_state_dir(self):
        """Create a temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def mock_memory(self):
        """Create a mock memory subsystem."""
        memory = MagicMock()
        memory.semantic_store = MagicMock()
        memory.semantic_store.add_claim = MagicMock()
        memory.episodic_store = None
        return memory
    
    @pytest.fixture
    def engine(self, mock_memory, temp_state_dir):
        """Create a DreamingEngine with mock memory."""
        return DreamingEngine(mock_memory, state_dir=temp_state_dir)
    
    def test_engine_initialization(self, engine, temp_state_dir):
        """Test engine initializes correctly."""
        assert engine.state_dir == temp_state_dir
        assert engine.state_dir.exists()
        assert engine.lookback_hours == 24
        assert engine.max_candidates == 100
    
    def test_record_recall(self, engine):
        """Test recording a recall."""
        engine.record_recall("test-hash-1", "what is python")
        engine.record_recall("test-hash-1", "tell me about python")
        engine.record_recall("test-hash-1", "python tutorial")
        
        stats = engine._recall_stats["test-hash-1"]
        assert stats["recall_count"] == 3
        assert len(stats["queries"]) == 3
        assert len(stats["recall_days"]) == 1  # All today
    
    def test_record_recall_different_days(self, engine):
        """Test recording recalls on different days."""
        import datetime
        
        # Record recall
        engine.record_recall("test-hash-2", "query 1")
        
        # Simulate next day
        stats = engine._recall_stats["test-hash-2"]
        yesterday = (datetime.datetime.now(timezone.utc) - datetime.timedelta(days=1)).date().isoformat()
        stats["recall_days"].append(yesterday)
        
        # Record another recall
        engine.record_recall("test-hash-2", "query 2")
        
        assert stats["recall_count"] == 2
        assert len(stats["recall_days"]) == 2
    
    def test_scoring_weights(self):
        """Test scoring weights are correctly defined."""
        assert SCORING_WEIGHTS["relevance"] == 0.30
        assert SCORING_WEIGHTS["frequency"] == 0.24
        assert SCORING_WEIGHTS["diversity"] == 0.15
        assert SCORING_WEIGHTS["recency"] == 0.15
        assert SCORING_WEIGHTS["consolidation"] == 0.10
        assert SCORING_WEIGHTS["conceptual"] == 0.06
        
        # Weights should sum to ~1.0
        total = sum(SCORING_WEIGHTS.values())
        assert 0.99 <= total <= 1.01
    
    def test_extract_concept_tags(self, engine):
        """Test concept tag extraction."""
        # Coding-related
        tags = engine._extract_concept_tags("I need help debugging this Python function")
        assert "coding" in tags
        assert "problem" in tags
        
        # Work-related
        tags = engine._extract_concept_tags("Let's schedule a meeting for the project deadline")
        assert "work" in tags
        assert "planning" in tags
        
        # Learning-related
        tags = engine._extract_concept_tags("Can you teach me about machine learning?")
        assert "learning" in tags
    
    def test_hash_content(self, engine):
        """Test content hashing."""
        hash1 = engine._hash_content("Hello World")
        hash2 = engine._hash_content("Hello World")
        hash3 = engine._hash_content("Different content")
        
        assert hash1 == hash2  # Same content = same hash
        assert hash1 != hash3  # Different content = different hash
        assert len(hash1) == 16
    
    def test_dedupe_candidates(self, engine):
        """Test candidate deduplication."""
        candidates = [
            DreamCandidate(content="Same content here", source="episodic", timestamp=1),
            DreamCandidate(content="Same content here but longer", source="episodic", timestamp=2),
            DreamCandidate(content="Different content", source="semantic", timestamp=3),
        ]
        
        unique = engine._dedupe_candidates(candidates)
        assert len(unique) == 2  # First two are duplicates
    
    def test_calculate_score(self, engine):
        """Test score calculation."""
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # High-scoring candidate
        candidate = DreamCandidate(
            content="Important work project discussion about Python coding deadline",
            source="episodic",
            timestamp=now.timestamp(),
            recall_count=5,
            last_recalled=now.timestamp(),
            daily_appearances=3,
            concept_tags=["work", "coding", "planning"],
        )
        
        # Add recall stats
        engine.record_recall(engine._hash_content(candidate.content), "python project")
        engine.record_recall(engine._hash_content(candidate.content), "coding help")
        engine.record_recall(engine._hash_content(candidate.content), "deadline")
        
        score = engine._calculate_score(candidate, now, ["work", "coding"])
        assert 0.0 <= score <= 1.0
        assert score > 0.5  # Should be high given good stats
    
    @pytest.mark.asyncio
    async def test_light_phase_empty(self, engine):
        """Test light phase with no events."""
        from datetime import datetime, timezone, timedelta
        
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        candidates = await engine._light_phase(since)
        
        # Should return empty list (no memory backend)
        assert isinstance(candidates, list)
    
    @pytest.mark.asyncio
    async def test_rem_phase(self, engine):
        """Test REM phase pattern detection."""
        candidates = [
            DreamCandidate(content="Python coding project deadline", source="episodic", timestamp=1),
            DreamCandidate(content="Python debugging help needed", source="episodic", timestamp=2),
            DreamCandidate(content="Python tutorial request", source="episodic", timestamp=3),
            DreamCandidate(content="Meeting schedule planning", source="episodic", timestamp=4),
        ]
        
        patterns = await engine._rem_phase(candidates)
        assert isinstance(patterns, list)
        # "coding" should appear as a pattern (3/4 candidates)
        assert "coding" in patterns
    
    @pytest.mark.asyncio
    async def test_deep_phase(self, engine):
        """Test DEEP phase scoring and promotion."""
        candidates = [
            DreamCandidate(
                content="Important recurring work topic",
                source="episodic",
                timestamp=datetime.now(timezone.utc).timestamp(),
                recall_count=3,
                concept_tags=["work"],
            ),
        ]
        
        # Set high recall count via stats
        engine.record_recall(engine._hash_content(candidates[0].content), "query")
        engine.record_recall(engine._hash_content(candidates[0].content), "query2")
        engine.record_recall(engine._hash_content(candidates[0].content), "query3")
        engine._enrich_with_recall_stats(candidates[0])
        
        promoted = await engine._deep_phase(candidates, ["work"])
        
        assert isinstance(promoted, list)
    
    @pytest.mark.asyncio
    async def test_full_dream_cycle(self, engine):
        """Test a complete dream cycle."""
        report = await engine.run_dream_cycle(since_hours=24)
        
        assert isinstance(report, DreamReport)
        assert report.phase == DreamPhase.DEEP
        assert report.duration_seconds >= 0
    
    def test_get_dreaming_status(self, temp_state_dir):
        """Test getting dreaming status."""
        status = get_dreaming_status(temp_state_dir)
        
        assert status["enabled"] is True
        assert status["tracked_memories"] == 0
        assert status["total_dream_cycles"] == 0
        assert status["last_dream_cycle"] is None


class TestDreamingEngineIntegration:
    """Integration-style tests for DreamingEngine."""
    
    @pytest.mark.asyncio
    async def test_dream_journal_created(self):
        """Test that dream journal is created after a cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = MagicMock()
            memory.semantic_store = MagicMock()
            
            engine = DreamingEngine(memory, state_dir=Path(tmpdir))
            await engine.run_dream_cycle(since_hours=1)
            
            journal_path = Path(tmpdir) / "DREAMS.md"
            assert journal_path.exists()
            content = journal_path.read_text()
            assert "Dream Cycle" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
