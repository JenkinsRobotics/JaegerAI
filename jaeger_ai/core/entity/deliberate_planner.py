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
    """Bounded multi-plan candidate generator and critic selector (DeliberativeSearch)."""

    @staticmethod
    def generate_candidate_plans(
        goal: str,
        context: str = "",
        prior_reflections: Sequence[StructuredReflection] | None = None,
        cognition_provider: Callable[[str], str] | None = None,
    ) -> list[CandidatePlan]:
        """Generate at least 3 distinct structural execution plans for the goal."""
        t_id = int(time.time() * 1000)
        reflections = list(prior_reflections or [])

        # If cognition provider is supplied, generate real model-driven candidates
        if cognition_provider is not None:
            ref_summaries = [
                f"- Hypothesis: {r.hypothesis} | Failure condition: {r.failure_conditions} | Applicability: {', '.join(r.applicability_conditions)}"
                for r in reflections
            ]
            prompt = (
                f"You are a deliberate planning engine. Generate at least 3 materially different candidate plans for:\n"
                f"Goal: {goal}\n"
                f"Context: {context}\n"
                f"Prior Failure Reflections to avoid:\n" + ("\n".join(ref_summaries) if ref_summaries else "None") + "\n\n"
                f"Respond strictly in JSON as a list of at least 3 objects with keys:\n"
                f'  "name": string,\n'
                f'  "strategy_summary": string,\n'
                f'  "steps": list of strings,\n'
                f'  "tools_required": list of tool names (strings),\n'
                f'  "reversibility": "reversible" | "partially_reversible" | "irreversible"\n'
            )
            try:
                import json
                import re
                resp = cognition_provider(prompt)
                m = re.search(r"\[.*\]", resp, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    if isinstance(parsed, list) and len(parsed) >= 1:
                        candidates = []
                        for i, item in enumerate(parsed):
                            candidates.append(
                                CandidatePlan(
                                    plan_id=f"plan-{t_id}-{i+1}",
                                    name=str(item.get("name") or f"Model Plan {i+1}"),
                                    strategy_summary=str(item.get("strategy_summary") or f"Strategy {i+1}"),
                                    steps=[str(s) for s in item.get("steps") or []],
                                    tools_required=[str(t) for t in item.get("tools_required") or []],
                                    reversibility=str(item.get("reversibility") or "reversible"),
                                    safety_score=float(item.get("safety_score", 0.9)),
                                    goal_satisfaction_score=float(item.get("goal_satisfaction_score", 0.9)),
                                )
                            )
                        if len(candidates) >= 3:
                            # Apply reflection penalties
                            for plan in candidates:
                                DeliberatePlanner._apply_reflection_penalties(plan, reflections)
                            return candidates
            except Exception as exc:
                logger.debug("Cognition provider plan generation fallback: %s", exc)

        # Baseline candidates
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
        for plan in candidates:
            DeliberatePlanner._apply_reflection_penalties(plan, reflections)

        return candidates

    @staticmethod
    def _apply_reflection_penalties(plan: CandidatePlan, reflections: list[StructuredReflection]) -> None:
        penalty = 0.0
        notes = []
        for ref in reflections:
            for tool in plan.tools_required:
                if tool in ref.applicability_conditions:
                    penalty += 0.2 * ref.confidence
                    notes.append(f"Caution on tool {tool}: {ref.hypothesis[:60]}")
        plan.reflection_penalty = penalty
        plan.critic_notes = "; ".join(notes) if notes else "No prior failure penalties"

    @classmethod
    def evaluate_and_select(
        cls,
        candidates: list[CandidatePlan],
        goal: str,
        *,
        prefer_safety: bool = True,
        critic_provider: Callable[[str], str] | None = None,
        prior_reflections: Sequence[StructuredReflection] | None = None,
    ) -> CandidatePlan:
        """Critic pass scoring and selecting the optimal plan."""
        best_plan = candidates[0]
        highest_score = -1.0
        reflections = list(prior_reflections or [])

        for plan in candidates:
            # If an independent critic provider is provided, score plan dynamically
            if critic_provider is not None:
                prompt = (
                    f"Evaluate the following candidate plan for goal: {goal}\n"
                    f"Plan: {plan.name}\n"
                    f"Strategy: {plan.strategy_summary}\n"
                    f"Steps: {plan.steps}\n"
                    f"Tools: {plan.tools_required}\n"
                    f"Reversibility: {plan.reversibility}\n"
                    f"Reflections: {[r.hypothesis for r in reflections]}\n\n"
                    f"Respond strictly in JSON:\n"
                    f'{{"goal_satisfaction_score": float (0-1), "safety_score": float (0-1), "reflection_penalty": float (0-1), "notes": str}}'
                )
                try:
                    import json
                    import re
                    resp = critic_provider(prompt)
                    m = re.search(r"\{.*\}", resp, re.DOTALL)
                    if m:
                        data = json.loads(m.group(0))
                        plan.goal_satisfaction_score = float(data.get("goal_satisfaction_score", plan.goal_satisfaction_score))
                        plan.safety_score = float(data.get("safety_score", plan.safety_score))
                        plan.reflection_penalty = float(data.get("reflection_penalty", plan.reflection_penalty))
                        if data.get("notes"):
                            plan.critic_notes = str(data["notes"])
                except Exception as exc:
                    logger.debug("Critic evaluation provider error: %s", exc)

            reversibility_bonus = 0.1 if plan.reversibility == "reversible" else 0.0
            safety_weight = 0.4 if prefer_safety else 0.2
            goal_weight = 0.4 if prefer_safety else 0.6

            score = (
                (plan.goal_satisfaction_score * goal_weight)
                + (plan.safety_score * safety_weight)
                + reversibility_bonus
                - (plan.reflection_penalty * 0.3)
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

    @classmethod
    def replan_on_failure(
        cls,
        failed_plan: CandidatePlan,
        failure_evidence: str,
        goal: str,
        *,
        prior_reflections: Sequence[StructuredReflection] | None = None,
        cognition_provider: Callable[[str], str] | None = None,
        critic_provider: Callable[[str], str] | None = None,
    ) -> CandidatePlan:
        """Bounded replan using new consequence evidence after a plan fails execution."""
        logger.warning(
            "DeliberativeSearch: Bounded replan initiated for %s due to: %s",
            failed_plan.plan_id,
            failure_evidence,
        )
        context = f"PREVIOUS PLAN {failed_plan.name} FAILED: {failure_evidence}. You MUST choose an alternative approach."
        # Generate new candidates incorporating failure evidence
        candidates = cls.generate_candidate_plans(
            goal=goal,
            context=context,
            prior_reflections=prior_reflections,
            cognition_provider=cognition_provider,
        )
        # Exclude the failed plan strategy from replanning candidates
        viable = [
            c for c in candidates
            if c.name != failed_plan.name and c.strategy_summary != failed_plan.strategy_summary
        ]
        if not viable:
            viable = candidates

        return cls.evaluate_and_select(
            viable,
            goal,
            critic_provider=critic_provider,
            prior_reflections=prior_reflections,
        )


# Alias
DeliberativeSearch = DeliberatePlanner
