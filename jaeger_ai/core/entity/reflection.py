"""Reflexion Layer: Structured Failure Hypotheses & Adaptive Retrieval (UPAA Principle 11/12).

Ported & Adapted from Reflexion (Noah Shinn et al., 2023 - MIT License):
Reference: .donors/reflexion @ commit 218cf0ef1df84b05ce379dd4a8e47f17766733a0

Invariants:
- A reflection is NOT a semantic fact. It is a working hypothesis with provenance and confidence.
- Reflections are generated upon objective failure or severe execution error.
- Future planning and turn cognition dynamically query applicable reflections to avoid repeating
  known failure modes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Sequence

from .events import JaegerEvent
from .verification import VerificationResult

logger = logging.getLogger("jaeger.entity.reflection")


@dataclass
class StructuredReflection:
    """A durable meta-cognitive hypothesis derived from failure experience."""

    reflection_id: str
    hypothesis: str
    confidence: float
    failure_conditions: str
    applicability_conditions: list[str] = field(default_factory=list)
    supporting_episode_ids: list[str] = field(default_factory=list)
    contradicting_episode_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuredReflection:
        return cls(**data)


class ReflexionStore:
    """Persistent store and semantic/keyword retriever for structured reflections."""

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self._store_file = state_root / "structured_reflections.json"
        self._reflections: list[StructuredReflection] = self._load()

    def _load(self) -> list[StructuredReflection]:
        if not self._store_file.exists():
            return []
        try:
            raw = json.loads(self._store_file.read_text(encoding="utf-8"))
            return [StructuredReflection.from_dict(item) for item in raw]
        except Exception as exc:
            logger.warning("Failed loading structured reflections from %s: %s", self._store_file, exc)
            return []

    def _save(self) -> None:
        try:
            self._store_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_file.with_suffix(".tmp")
            raw = [r.to_dict() for r in self._reflections]
            tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            tmp.replace(self._store_file)
        except Exception as exc:
            logger.error("Failed saving structured reflections: %s", exc)

    def add_reflection(self, reflection: StructuredReflection) -> None:
        # Check if an existing reflection addresses the same failure conditions
        for idx, existing in enumerate(self._reflections):
            if existing.failure_conditions == reflection.failure_conditions:
                # Merge episode provenance and adjust confidence
                supporting = list(set(existing.supporting_episode_ids + reflection.supporting_episode_ids))
                updated = StructuredReflection(
                    reflection_id=existing.reflection_id,
                    hypothesis=reflection.hypothesis,
                    confidence=min(0.95, existing.confidence + 0.1),
                    failure_conditions=existing.failure_conditions,
                    applicability_conditions=list(set(existing.applicability_conditions + reflection.applicability_conditions)),
                    supporting_episode_ids=supporting,
                    contradicting_episode_ids=existing.contradicting_episode_ids,
                    created_at=existing.created_at,
                    updated_at=time.time(),
                )
                self._reflections[idx] = updated
                self._save()
                return

        self._reflections.append(reflection)
        self._save()

    def record_contradiction(self, reflection_id: str, episode_id: str) -> None:
        """When an action succeeds despite a failure hypothesis, lower confidence."""
        for idx, r in enumerate(self._reflections):
            if r.reflection_id == reflection_id:
                contradicting = list(set(r.contradicting_episode_ids + [episode_id]))
                new_conf = max(0.1, r.confidence - 0.2)
                self._reflections[idx] = StructuredReflection(
                    reflection_id=r.reflection_id,
                    hypothesis=r.hypothesis,
                    confidence=new_conf,
                    failure_conditions=r.failure_conditions,
                    applicability_conditions=r.applicability_conditions,
                    supporting_episode_ids=r.supporting_episode_ids,
                    contradicting_episode_ids=contradicting,
                    created_at=r.created_at,
                    updated_at=time.time(),
                )
                self._save()
                return

    def retrieve_applicable(
        self,
        intent_or_prompt: str,
        tool_names: Sequence[str] | None = None,
        *,
        min_confidence: float = 0.3,
        limit: int = 5,
    ) -> list[StructuredReflection]:
        """Retrieve stored failure hypotheses that match the incoming task context or proposed tools."""
        results: list[tuple[float, StructuredReflection]] = []
        tokens = set(re.findall(r"\b\w{3,}\b", intent_or_prompt.lower()))
        tool_set = set(tool_names or [])

        for r in self._reflections:
            if r.confidence < min_confidence:
                continue

            score = 0.0
            # Check applicability conditions (keywords/tags)
            for cond in r.applicability_conditions:
                cond_l = cond.lower()
                if cond_l in tool_set:
                    score += 2.0
                if cond_l in tokens:
                    score += 1.0

            # Check textual overlap in failure condition or hypothesis
            fail_tokens = set(re.findall(r"\b\w{3,}\b", r.failure_conditions.lower()))
            overlap = len(tokens.intersection(fail_tokens))
            score += overlap * 0.5

            if score > 0.0:
                results.append((score * r.confidence, r))

        results.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in results[:limit]]

    def to_prompt_context_block(self, intent_or_prompt: str, tool_names: Sequence[str] | None = None) -> str:
        """Render relevant failure warnings to inject into prompt context."""
        applicable = self.retrieve_applicable(intent_or_prompt, tool_names)
        if not applicable:
            return ""

        lines = ["# Retrieved Failure Hypotheses & Lessons (Reflexion):"]
        for r in applicable:
            lines.append(
                f"- [Warning / Confidence {r.confidence:.2f}] When handling {', '.join(r.applicability_conditions)}: "
                f"{r.hypothesis} (Observed in episode(s): {', '.join(r.supporting_episode_ids[-2:])})"
            )
        return "\n".join(lines)


def formulate_reflection_from_failure(
    event: JaegerEvent,
    verification: VerificationResult,
) -> StructuredReflection:
    """Deterministically synthesize a structured reflection hypothesis from verified failure evidence."""
    tool_name = str(event.payload.get("tool") or event.payload.get("tool_name") or "action")
    error_msg = verification.error or verification.evidence
    
    # Extract applicability keywords
    conditions = [tool_name]
    if "git" in tool_name:
        conditions.extend(["version_control", "repository"])
    if "file" in tool_name or "path" in str(event.payload):
        conditions.extend(["filesystem", "file_io"])
    if "network" in error_msg.lower() or "timeout" in error_msg.lower():
        conditions.append("network")

    hypothesis = (
        f"Operation {tool_name} failed objective ({verification.target_objective}): {error_msg}. "
        f"Prior to repeating, independently verify preconditions and validate inputs."
    )

    return StructuredReflection(
        reflection_id=f"refl-{int(time.time()*1000)}",
        hypothesis=hypothesis,
        confidence=0.7,
        failure_conditions=f"{tool_name}:{error_msg[:120]}",
        applicability_conditions=list(set(conditions)),
        supporting_episode_ids=[event.event_id],
    )
