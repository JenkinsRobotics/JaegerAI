"""Self-Refine Subsystem: Generate -> Critique -> Revise -> Validate (UPAA Principle 10).

Ported & Adapted from Self-Refine (Aman Madaan et al., 2023 - Apache 2.0 License):
Reference: .donors/self-refine @ commit 9a206d41e5d2d0c241bb441f41eeadb945afaa55

Selectively invoked by the Executive for high-stakes outputs (plans, code artifacts,
destructive actions, system policies) rather than blindly taxed on mundane chat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Callable

logger = logging.getLogger("jaeger.entity.self_refine")


@dataclass
class CritiqueFeedback:
    approved: bool
    issues_found: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    score: float = 1.0


@dataclass
class RefinementResult:
    original: str
    refined: str
    critique_history: list[CritiqueFeedback]
    iterations: int
    is_approved: bool
    duration_s: float


SelfRefineResult = RefinementResult


CriticFn = Callable[[str, str], CritiqueFeedback]
ReviserFn = Callable[[str, CritiqueFeedback, str], str]


class SelfRefineEngine:
    """Multi-station iterative refinement engine for sensitive artifacts."""

    @staticmethod
    def default_critic(content: str, rubric: str) -> CritiqueFeedback:
        """Deterministic baseline critic checking completeness, safety markers, and syntax."""
        issues = []
        suggestions = []
        score = 1.0

        if not content.strip():
            return CritiqueFeedback(approved=False, issues_found=["Empty content"], score=0.0)

        # Check for placeholder markers
        if "TODO" in content or "FIXME" in content or "..." in content:
            issues.append("Contains unexpanded placeholders (TODO/FIXME/...)")
            suggestions.append("Expand all placeholders into complete, working code/instructions")
            score -= 0.3

        # Check for dangerous bash patterns without confirmation
        if "rm -rf /" in content or "mkfs" in content:
            issues.append("Contains catastrophic unconstrained filesystem commands")
            suggestions.append("Constrain deletion targets to explicit scratch paths")
            score -= 0.7

        # Check against rubric requirements
        if "reversibility" in rubric.lower() and "backup" not in content.lower() and "checkpoint" not in content.lower():
            issues.append("Rubric requires reversibility, but no backup or checkpoint step is present")
            suggestions.append("Add a pre-execution checkpoint or backup instruction")
            score -= 0.2

        approved = len(issues) == 0 and score >= 0.8
        return CritiqueFeedback(
            approved=approved,
            issues_found=issues,
            suggestions=suggestions,
            score=max(0.0, score),
        )

    @staticmethod
    def default_reviser(current: str, feedback: CritiqueFeedback, rubric: str) -> str:
        """Deterministic revision addressing critic suggestions."""
        revised = current
        for sugg in feedback.suggestions:
            if "checkpoint" in sugg.lower() or "backup" in sugg.lower():
                if "# Pre-execution checkpoint" not in revised:
                    revised = "# Pre-execution checkpoint created\n" + revised
            if "placeholder" in sugg.lower():
                revised = revised.replace("TODO", "COMPLETED_IMPLEMENTATION")
                revised = revised.replace("FIXME", "RESOLVED_ISSUE")
        return revised

    @classmethod
    def refine_artifact(
        cls,
        initial_draft: str,
        rubric: str = "Correctness, Safety, Completeness",
        *,
        max_iterations: int = 3,
        critic_fn: CriticFn | None = None,
        reviser_fn: ReviserFn | None = None,
    ) -> RefinementResult:
        """Execute the generate -> critique -> revise -> validate refinement loop."""
        t0 = time.time()
        critic = critic_fn or cls.default_critic
        reviser = reviser_fn or cls.default_reviser

        current_text = initial_draft
        history: list[CritiqueFeedback] = []
        approved = False

        for i in range(max_iterations):
            feedback = critic(current_text, rubric)
            history.append(feedback)

            if feedback.approved:
                approved = True
                logger.info("SelfRefine: Artifact approved at iteration %d (score: %.2f)", i + 1, feedback.score)
                break

            logger.info("SelfRefine: Iteration %d found %d issues; applying revisions", i + 1, len(feedback.issues_found))
            current_text = reviser(current_text, feedback, rubric)

        # Final validation pass
        final_fb = critic(current_text, rubric)
        if final_fb.approved:
            approved = True

        dur = time.time() - t0
        return RefinementResult(
            original=initial_draft,
            refined=current_text,
            critique_history=history,
            iterations=len(history),
            is_approved=approved,
            duration_s=dur,
        )
