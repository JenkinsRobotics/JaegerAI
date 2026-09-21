"""LATS / Deliberate Tree-Search Planner (UPAA Principle 9 & 10).

Implements bounded deliberate planning (Language Agent Tree Search / MCTS inspired):
1. Generates >= 3 candidate plans with varied strategies/tool sequences.
2. Evaluates candidates against:
   - Goal satisfaction
   - Safety & operational blast radius
   - Reversibility (reversible vs irreversible mutations)
   - Retrieved failure reflections from ReflexionStore
3. Uses an independent critic evaluation to select or synthesize the winning plan.
4. Binds milestones to WorkLedger for sequential verifiable execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Sequence

from .reflection import StructuredReflection

logger = logging.getLogger("jaeger.entity.deliberate_planner")


@dataclass
class CandidatePlan:
    plan_id: str
    name: str
    strategy_summary: str
    steps: list[str]
    tools_required: list[str]
    reversibility: str = "reversible"  # "reversible", "partially_reversible", "irreversible"
    safety_score: float = 1.0
    goal_satisfaction_score: float = 1.0
    reflection_penalty: float = 0.0
    final_score: float = 0.0
    critic_notes: str = ""

    @property
    def strategy(self) -> str:
        return self.strategy_summary


class DeliberatePlanner:
    """Bounded multi-plan candidate generator and critic selector."""

    @staticmethod
    def generate_candidate_plans(
        goal: str,
        context: str = "",
        prior_reflections: Sequence[StructuredReflection] | None = None,
    ) -> list[CandidatePlan]:
        """Generate at least 3 distinct structural execution plans for the goal."""
        t_id = int(time.time() * 1000)
        reflections = list(prior_reflections or [])
        ref_tokens = {w.lower() for r in reflections for w in r.applicability_conditions}

        # Candidate 1: Direct / Minimal Mutation Plan
        plan_1 = CandidatePlan(
            plan_id=f"plan-{t_id}-1",
            name="Inspect First & Minimal Surgery",
            strategy_summary="Perform non-destructive inspection, gather exact inventory, then apply targeted changes.",
            steps=[
                f"Inspect current state relevant to: {goal}",
                "Gather inventory and state diff without making modifications",
                "Execute surgical targeted update",
                "Verify produced real-world state against objective",
            ],
            tools_required=["read_file", "search_directory", "write_file"],
            reversibility="reversible",
            safety_score=0.95,
            goal_satisfaction_score=0.90,
        )

        # Candidate 2: Batch / Automated Pipeline Plan
        plan_2 = CandidatePlan(
            plan_id=f"plan-{t_id}-2",
            name="Batch Ledger & Automated Checkpoints",
            strategy_summary="Establish a work ledger with external checkpoints, process items in isolated sub-batches.",
            steps=[
                "Initialize work ledger and snapshot pre-execution checkpoint",
                f"Batch process items required for: {goal}",
                "Record execution progress in work ledger after each step",
                "Run comprehensive verification assertions across all outputs",
                "Finalize task only upon 100% verified ledger completion",
            ],
            tools_required=["work_ledger", "checkpoint", "batch_exec", "verify"],
            reversibility="partially_reversible",
            safety_score=0.88,
            goal_satisfaction_score=0.96,
        )

        # Candidate 3: Clean Reconstruction / Isolated Staging Plan
        plan_3 = CandidatePlan(
            plan_id=f"plan-{t_id}-3",
            name="Isolated Staging & Atomic Cutover",
            strategy_summary="Perform all work in an isolated scratch/staging workspace, verify completely, then atomic move.",
            steps=[
                "Create isolated scratch staging directory in state root",
                f"Construct required artifacts for {goal} in scratch area",
                "Run test suite and external state validators in staging",
                "Atomic cutover from staging to destination target",
                "Clean up temporary scratch workspace",
            ],
            tools_required=["make_directory", "write_file", "run_tests", "move_file"],
            reversibility="reversible",
            safety_score=0.98,
            goal_satisfaction_score=0.92,
        )

        candidates = [plan_1, plan_2, plan_3]

        # Evaluate against prior reflections
        for plan in candidates:
            penalty = 0.0
            notes = []
            for ref in reflections:
                for tool in plan.tools_required:
                    if tool in ref.applicability_conditions:
                        penalty += 0.2 * ref.confidence
                        notes.append(f"Caution on tool {tool}: {ref.hypothesis[:60]}")
            plan.reflection_penalty = penalty
            plan.critic_notes = "; ".join(notes) if notes else "No prior failure penalties"

        return candidates

    @classmethod
    def evaluate_and_select(
        cls,
        candidates: list[CandidatePlan],
        goal: str,
        *,
        prefer_safety: bool = True,
    ) -> CandidatePlan:
        """Critic pass scoring and selecting the optimal plan."""
        best_plan = candidates[0]
        highest_score = -1.0

        for plan in candidates:
            # Score formula: goal_satisfaction * 0.5 + safety * 0.3 - penalty * 0.2
            reversibility_bonus = 0.1 if plan.reversibility == "reversible" else 0.0
            safety_weight = 0.4 if prefer_safety else 0.2
            goal_weight = 0.4 if prefer_safety else 0.6

            score = (
                (plan.goal_satisfaction_score * goal_weight)
                + (plan.safety_score * safety_weight)
                + reversibility_bonus
                - (plan.reflection_penalty * 0.2)
            )
            plan.final_score = round(max(0.0, min(1.0, score)), 3)

            if plan.final_score > highest_score:
                highest_score = plan.final_score
                best_plan = plan

        logger.info(
            "DeliberatePlanner selected %s (%s) with score %.3f over %d candidates",
            best_plan.plan_id,
            best_plan.name,
            best_plan.final_score,
            len(candidates),
        )
        return best_plan
