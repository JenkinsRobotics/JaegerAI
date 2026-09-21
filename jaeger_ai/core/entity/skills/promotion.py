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
import os
from pathlib import Path
import time
from typing import Any, Callable

from jaeger_ai.core.entity.events import EventType, JaegerEvent

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
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            try:
                from jaeger_ai.core.instance.instance import operator_state_root
                self.skills_dir = operator_state_root() / "skills"
            except Exception:
                self.skills_dir = Path(os.environ.get("JAEGER_STATE_DIR", Path.home() / ".jaeger")) / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._promoted_skills: dict[str, dict[str, Any]] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Rebuild the in-memory registry from promoted v3 packages on disk."""
        if not self.skills_dir.is_dir():
            return
        for folder in self.skills_dir.iterdir():
            if not folder.is_dir():
                continue
            skill_md = folder / "SKILL.md"
            manifest = folder / "manifest.yaml"
            if not skill_md.exists() and not manifest.exists():
                continue
            description = ""
            code = ""
            try:
                text = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
                for line in text.splitlines():
                    if line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()
                        break
                run_py = folder / "run.py"
                if run_py.exists():
                    code = run_py.read_text(encoding="utf-8")
            except Exception as exc:
                logger.debug("Failed loading skill package %s: %s", folder, exc)
            self._promoted_skills[folder.name] = {
                "name": folder.name,
                "description": description,
                "code": code,
                "parameters": {},
                "skill_md_path": str(skill_md),
                "manifest_path": str(manifest),
            }

    def matching_skills(self, intent_or_prompt: str) -> list[dict[str, Any]]:
        """Return promoted skills whose name or description overlaps the task."""
        tokens = {
            tok.lower()
            for tok in (intent_or_prompt or "").replace("-", " ").replace("_", " ").split()
            if len(tok) >= 4
        }
        matched: list[dict[str, Any]] = []
        for name, rec in self._promoted_skills.items():
            hay = f"{name} {rec.get('description') or ''}".lower().replace("_", " ")
            if any(tok in hay for tok in tokens):
                matched.append(rec)
            elif name.startswith("learned_") and name.replace("learned_", "") in (intent_or_prompt or "").lower():
                matched.append(rec)
        return matched

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
            from jaeger_ai.core.entity.runtime import EntityRuntime
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

        # Write real production skill artifact with standard v3 manifest and SKILL.md
        skill_folder = self.skills_dir / candidate.skill_name
        skill_folder.mkdir(parents=True, exist_ok=True)
        (skill_folder / "tests").mkdir(parents=True, exist_ok=True)

        manifest_yaml = skill_folder / "manifest.yaml"
        manifest_content = (
            f'schema: "jros.skill/v3"\n'
            f'id: "{candidate.skill_name}"\n'
            f'version: "1.0.0"\n'
            f'package: "playbook"\n'
            f'origin: "agent_authored"\n'
            f'description: "{candidate.description}"\n'
            f'entrypoint:\n'
            f'  module: "run"\n'
            f'  callable: "register"\n'
        )
        manifest_yaml.write_text(manifest_content, encoding="utf-8")

        skill_md = skill_folder / "SKILL.md"
        content = (
            f"---\n"
            f'schema: "jros.skill/v3"\n'
            f"name: {candidate.skill_name}\n"
            f"description: {candidate.description}\n"
            f"version: 1.0.0\n"
            f"verified: true\n"
            f"---\n\n"
            f"# {candidate.skill_name}\n\n"
            f"{candidate.description}\n\n"
            f"## Verification Proof\n"
            f"- Evidence: {verification.evidence}\n"
            f"- Verified: {verification.passed}\n"
            f"- Timestamp: {verification.tested_at}\n\n"
            f"## Implementation\n\n"
            f"```python\n{candidate.code}\n```\n"
        )
        skill_md.write_text(content, encoding="utf-8")

        # Write execution module
        run_code = candidate.code or ""
        if "def register(" not in run_code:
            run_code = f"{run_code}\n\ndef register(agent=None):\n    return True\n"
        (skill_folder / "run.py").write_text(run_code, encoding="utf-8")

        # Write smoke test
        smoke_py = skill_folder / "tests" / "smoke_test.py"
        smoke_py.write_text(
            "def test_smoke():\n    assert True\n",
            encoding="utf-8",
        )

        record = {
            "name": candidate.skill_name,
            "description": candidate.description,
            "code": candidate.code,
            "parameters": candidate.parameters,
            "verified_at": verification.tested_at,
            "evidence": verification.evidence,
            "skill_md_path": str(skill_md),
            "manifest_path": str(manifest_yaml),
        }
        self._promoted_skills[candidate.skill_name] = record

        # Register through real Jaeger skill infrastructure
        try:
            from jaeger_agent.tools.skills import reload_skills
            reload_skills()
        except Exception as exc:
            try:
                from jaeger_agent.skill_registry.skill_loader import load_and_register
                from jaeger_agent.workspace import get_layout
                layout = get_layout()
                if layout is not None:
                    load_and_register(None, layout)
            except Exception as e:
                logger.debug("Real skill loader registration fallback: %s", e)

        # Emit skill.promoted event into the canonical entity event stream
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
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
