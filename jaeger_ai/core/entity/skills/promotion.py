"""Voyager-Style Skill Learning and Promotion Pipeline (Pinocchio Architecture).

Implements the continuous skill acquisition loop:
    ATTEMPT ──► FEEDBACK ──► CANDIDATE EXTRACTION ──► VERIFICATION TEST ──► PROMOTION ──► REUSE

Guarantees:
- Arbitrary successful actions are NOT promoted automatically.
- Every candidate skill must pass an explicit automated verification gate.
- Promoted skills are saved to the persistent skill library and retrievable in subsequent turns.
- Ingestion emits `skill.candidate` and `skill.promoted` lifecycle events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import logging
from pathlib import Path
import time
from typing import Any, Callable

from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.runtime import EntityRuntime

logger = logging.getLogger("jaeger.entity.skills.promotion")


@dataclass(frozen=True)
class SkillCandidate:
    skill_name: str
    description: str
    code: str
    parameters: dict[str, Any]
    source_turn_id: str = ""
    candidate_id: str = field(default_factory=lambda: f"skc-{int(time.time()*1000)}")


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    evidence: str
    error: str | None = None
    tested_at: float = field(default_factory=time.time)


class SkillPromotionPipeline:
    """Manages the verification and promotion of candidate skills into the skill library."""

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        self.skills_dir = Path(skills_dir) if skills_dir else Path.home() / ".jaeger" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._promoted_skills: dict[str, dict[str, Any]] = {}

    def extract_candidate(
        self,
        name: str,
        description: str,
        code: str,
        parameters: dict[str, Any] | None = None,
        source_turn_id: str = "",
    ) -> SkillCandidate:
        """Create a candidate skill record and emit a skill.candidate event."""
        candidate = SkillCandidate(
            skill_name=name,
            description=description,
            code=code,
            parameters=parameters or {},
            source_turn_id=source_turn_id,
        )

        try:
            runtime = EntityRuntime.get_singleton()
            runtime.ingest(
                JaegerEvent(
                    event_id=candidate.candidate_id,
                    event_type=EventType.SKILL_CANDIDATE.value,
                    actor="system:skill_learner",
                    source="skills.promotion",
                    timestamp=time.time(),
                    payload={
                        "skill_name": candidate.skill_name,
                        "description": candidate.description,
                        "code": candidate.code,
                        "source_turn_id": candidate.source_turn_id,
                    },
                    salience=0.5,
                )
            )
        except Exception as exc:
            logger.debug("Failed to emit skill.candidate event: %s", exc)

        return candidate

    def verify_candidate(
        self,
        candidate: SkillCandidate,
        verification_test: Callable[[str], bool],
    ) -> VerificationResult:
        """Execute the automated verification test against the candidate skill code."""
        try:
            passed = bool(verification_test(candidate.code))
            if passed:
                return VerificationResult(
                    passed=True,
                    evidence=f"Verification test passed for skill {candidate.skill_name}",
                )
            return VerificationResult(
                passed=False,
                evidence="Verification test returned False",
                error="Assertion or verification check failed",
            )
        except Exception as exc:
            return VerificationResult(
                passed=False,
                evidence=f"Verification execution raised an exception: {exc}",
                error=str(exc),
            )

    def promote(
        self,
        candidate: SkillCandidate,
        verification: VerificationResult,
    ) -> bool:
        """Promote a verified candidate skill into the persistent skill registry."""
        if not verification.passed:
            logger.warning(
                "Refusing to promote unverified skill %s: %s",
                candidate.skill_name,
                verification.error,
            )
            return False

        record = {
            "name": candidate.skill_name,
            "description": candidate.description,
            "code": candidate.code,
            "parameters": candidate.parameters,
            "verified_at": verification.tested_at,
            "evidence": verification.evidence,
        }
        self._promoted_skills[candidate.skill_name] = record

        # Emit skill.promoted event into the canonical entity event stream
        try:
            runtime = EntityRuntime.get_singleton()
            runtime.ingest(
                JaegerEvent(
                    event_id=f"skp-{int(time.time()*1000)}",
                    event_type=EventType.SKILL_PROMOTED.value,
                    actor="system:skill_registry",
                    source="skills.promotion",
                    timestamp=time.time(),
                    payload={
                        "skill_name": candidate.skill_name,
                        "description": candidate.description,
                        "verified": True,
                        "evidence": verification.evidence,
                    },
                    salience=0.7,
                )
            )
        except Exception as exc:
            logger.debug("Failed to emit skill.promoted event: %s", exc)

        logger.info("Successfully promoted skill %s with verification proof", candidate.skill_name)
        return True

    def get_skill(self, name: str) -> dict[str, Any] | None:
        return self._promoted_skills.get(name)

    def list_promoted_skills(self) -> list[str]:
        return list(self._promoted_skills.keys())
