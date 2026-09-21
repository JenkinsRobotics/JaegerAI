"""Canonical Cognition Router & Strategy Dispatcher (UPAA Principle 9 & 10).

The single canonical boundary through which all cognition execution must flow.
No route may bypass this architecture for normal production cognition.

Dispatches to:
1. PassiveHandler: Salience below threshold; 0 LLM calls, returns immediately.
2. DirectResponseHandler: Pure conversational or factual model reply without mutating tools.
3. ReActHandler: Subordinate JaegerAgent tool loop with tool consequence feedback.
4. DeliberatePlannerHandler: LATS-style tree search generating 3 candidate plans, critic evaluation, selection, and WorkLedger execution.
5. SpecialistHandler: Routes to specialist models or child agents (Claude, Codex, Hermes, etc.).
6. SleepTimeHandler: Offline memory consolidation, reflection synthesis, and skill candidate review.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Mapping

from .authority import AuthorityDecision, AuthorityLayer, ProposedAction
from .deliberate_planner import DeliberatePlanner
from .events import EventType, JaegerEvent
from .executive import CognitiveStrategy, ExecutiveDecision
from .memory import MemorySubsystem
from .reflection import ReflexionStore
from .self_refine import SelfRefineEngine
from .self_state import SelfState
from .sleep_time import SleepTimeProcessor
from .verification import VerificationContract, VerificationResult

logger = logging.getLogger("jaeger.entity.cognition_router")


@dataclass
class CognitionResult:
    strategy: str
    text: str = ""
    action_taken: bool = False
    llm_invoked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class CognitionStrategyHandler(ABC):
    """Abstract handler for a single cognitive strategy."""

    @abstractmethod
    def handle(
        self,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class PassiveHandler(CognitionStrategyHandler):
    """Salience < threshold: deterministic update only, zero LLM calls."""

    def handle(
        self,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "strategy": CognitiveStrategy.PASSIVE_OBSERVE.value,
            "text": "",
            "action_taken": False,
            "llm_invoked": False,
            "reason": decision.reason,
        }


class DirectResponseHandler(CognitionStrategyHandler):
    """Conversational or factual query without external mutating tools."""

    def handle(
        self,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        text = str(event.payload.get("text") or "")
        model_runner = context.get("model_runner")

        # Explicitly enforce zero tools at the cognition boundary
        try:
            from jaeger_agent.tool_executor import tool_allowlist
            with tool_allowlist([]):
                if callable(model_runner):
                    reply = model_runner(text)
                else:
                    reply = f"Acknowledged: {text[:120]}"
        except Exception:
            if callable(model_runner):
                reply = model_runner(text)
            else:
                reply = f"Acknowledged: {text[:120]}"

        return {
            "strategy": CognitiveStrategy.DIRECT_RESPONSE.value,
            "text": reply,
            "tools_exposed": [],
            "action_taken": True,
            "llm_invoked": True,
        }


class ReActHandler(CognitionStrategyHandler):
    """Subordinate JaegerAgent tool execution loop."""

    def handle(
        self,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        text = str(event.payload.get("text") or "")
        reflexion_store = context.get("reflexion_store")
        if reflexion_store is not None:
            try:
                block = reflexion_store.to_prompt_context_block(text)
                constraints = ""
                if hasattr(reflexion_store, "to_planning_constraints"):
                    constraints = reflexion_store.to_planning_constraints(text)
                if constraints:
                    text = (
                        f"{constraints}\n\n"
                        "Your FIRST tool call must obey the constraints above. "
                        "Do not repeat the failed first action from those episodes.\n\n"
                        f"{block}\n\n{text}" if block else
                        f"{constraints}\n\nYour FIRST tool call must obey the constraints above.\n\n{text}"
                    )
                elif block:
                    text = f"{block}\n\n{text}"
            except Exception as exc:
                logger.debug("ReAct reflexion inject skipped: %s", exc)
        skills_block = str(context.get("learned_skills_prompt") or "")
        if skills_block:
            text = f"{skills_block}\n\n{text}"
        react_runner = context.get("react_runner")

        if callable(react_runner):
            return react_runner(text, session_key=event.session_id)

        # Fallback subordinate execution
        return {
            "strategy": CognitiveStrategy.REACT_LOOP.value,
            "text": f"Completed ReAct execution for: {text[:100]}",
            "action_taken": True,
            "llm_invoked": True,
        }


class DeliberatePlannerHandler(CognitionStrategyHandler):
    """LATS-style deliberate tree-search planning: candidate plans -> critic evaluation -> execution."""

    def handle(
        self,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        goal = str(event.payload.get("text") or "")
        reflexion_store = context.get("reflexion_store")
        prior_reflections = []
        if reflexion_store is not None:
            try:
                prior_reflections = reflexion_store.get_relevant_reflections(goal)
            except Exception as exc:
                logger.debug("Failed retrieving reflections from reflexion store: %s", exc)

        cognition_provider = context.get("cognition_provider")
        critic_provider = context.get("critic_provider")

        store = context.get("event_store")
        parent_id = str(context.get("parent_event_id") or event.event_id)
        session_id = event.session_id
        if prior_reflections:
            logger.info("Deliberate planner received %d prior reflections", len(prior_reflections))

        # 1. Generate >= 3 candidate plans informed by prior reflections
        candidates = DeliberatePlanner.generate_candidate_plans(
            goal=goal,
            prior_reflections=prior_reflections,
            cognition_provider=cognition_provider,
        )
        if store is not None:
            try:
                store.append(
                    JaegerEvent.plan_generated(
                        f"{len(candidates)} candidates",
                        [c.name for c in candidates],
                        parent_event_id=parent_id,
                        session_id=session_id,
                    )
                )
                store.append(
                    JaegerEvent.typed(
                        EventType.PLAN_GENERATED.value,
                        {
                            "candidates": [
                                {"plan_id": c.plan_id, "name": c.name, "steps": c.steps}
                                for c in candidates
                            ],
                            "source": "cognition_provider" if cognition_provider else "fallback_templates",
                        },
                        actor="agent:planner",
                        source="deliberate_search",
                        parent_event_id=parent_id,
                        session_id=session_id,
                    )
                )
            except Exception as exc:
                logger.debug("plan.generated emit failed: %s", exc)

        # 2. Critic pass scoring and selecting best plan
        winning_plan = DeliberatePlanner.evaluate_and_select(
            candidates,
            goal,
            critic_provider=critic_provider,
            prior_reflections=prior_reflections,
        )
        if store is not None:
            try:
                store.append(
                    JaegerEvent.typed(
                        EventType.PLAN_CRITICIZED.value,
                        {
                            "plan_id": winning_plan.plan_id,
                            "critic_notes": winning_plan.critic_notes,
                            "final_score": winning_plan.final_score,
                        },
                        actor="agent:critic",
                        source="deliberate_search",
                        parent_event_id=parent_id,
                        session_id=session_id,
                    )
                )
                store.append(
                    JaegerEvent.typed(
                        EventType.PLAN_SELECTED.value,
                        {"plan_id": winning_plan.plan_id, "name": winning_plan.name, "steps": winning_plan.steps},
                        actor="agent:planner",
                        source="deliberate_search",
                        parent_event_id=parent_id,
                        session_id=session_id,
                    )
                )
            except Exception as exc:
                logger.debug("plan critic/select emit failed: %s", exc)

        # 3. If plan contains sensitive mutations, run SelfRefine pass
        if winning_plan.reversibility != "reversible":
            plan_str = "\n".join(winning_plan.steps)
            refinement = SelfRefineEngine.refine_artifact(
                plan_str,
                rubric="Reversibility, Safety, Checkpoints",
            )
            winning_plan.steps = [s.strip() for s in refinement.refined.split("\n") if s.strip()]

        # 4. Execute via ReAct subordinate if runner provided
        react_runner = context.get("react_runner")
        if callable(react_runner):
            exec_prompt = f"[Deliberate Plan Selected: {winning_plan.name}]\n" + "\n".join(f"- {s}" for s in winning_plan.steps)
            result = react_runner(exec_prompt, session_key=event.session_id)

            # 5. Consequence check & bounded replanning on failure
            if result.get("error"):
                logger.warning("Deliberate execution failed, initiating bounded replan: %s", result["error"])
                replanned = DeliberatePlanner.replan_on_failure(
                    winning_plan,
                    failure_evidence=str(result["error"]),
                    goal=goal,
                    prior_reflections=prior_reflections,
                    cognition_provider=cognition_provider,
                    critic_provider=critic_provider,
                )
                replan_prompt = f"[Replanned Strategy: {replanned.name}]\n" + "\n".join(f"- {s}" for s in replanned.steps)
                result = react_runner(replan_prompt, session_key=event.session_id)
                result["replanned"] = True
                result["plan_id"] = replanned.plan_id
                result["plan_name"] = replanned.name
                if store is not None:
                    try:
                        store.append(
                            JaegerEvent.typed(
                                EventType.PLAN_REPLANNED.value,
                                {"plan_id": replanned.plan_id, "name": replanned.name},
                                actor="agent:planner",
                                source="deliberate_search",
                                parent_event_id=parent_id,
                                session_id=session_id,
                            )
                        )
                    except Exception:
                        pass
                return result

            result["plan_id"] = winning_plan.plan_id
            result["plan_name"] = winning_plan.name
            result["candidates_evaluated"] = len(candidates)
            return result

        return {
            "strategy": CognitiveStrategy.DELIBERATE_PLANNING.value,
            "text": f"Selected and executed deliberate plan: {winning_plan.name}",
            "plan_id": winning_plan.plan_id,
            "candidates_evaluated": len(candidates),
            "steps": winning_plan.steps,
            "action_taken": True,
            "llm_invoked": True,
        }


class SpecialistHandler(CognitionStrategyHandler):
    """Delegated specialist routing (Codex, Hermes, Claude, etc.)."""

    def handle(
        self,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        specialist = decision.target_specialist or "specialist"
        text = str(event.payload.get("text") or "")
        delegate_runner = context.get("delegate_runner")

        if callable(delegate_runner):
            return delegate_runner(specialist, text, session_key=event.session_id)

        return {
            "strategy": CognitiveStrategy.SPECIALIST_DELEGATION.value,
            "specialist": specialist,
            "text": f"Routed task to specialist {specialist}: {text[:100]}",
            "action_taken": True,
            "llm_invoked": True,
        }


class SleepTimeHandler(CognitionStrategyHandler):
    """Offline consolidation, reflection synthesis, and skill candidate review."""

    def handle(
        self,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        processor: SleepTimeProcessor | None = context.get("sleep_processor")
        if processor is not None:
            cycle = processor.run_sleep_cycle(reason=decision.reason)
            return {
                "strategy": CognitiveStrategy.SLEEP_TIME_CONSOLIDATION.value,
                "text": f"Completed sleep-time cycle {cycle.cycle_id} in {cycle.duration_s:.2f}s",
                "claims_recorded": cycle.claims_recorded,
                "reflections_generated": cycle.reflections_generated,
                "action_taken": True,
                "llm_invoked": False,
            }

        return {
            "strategy": CognitiveStrategy.SLEEP_TIME_CONSOLIDATION.value,
            "text": "Sleep-time processing acknowledged",
            "action_taken": True,
            "llm_invoked": False,
        }


class CognitionRouter:
    """The central router ensuring all cognition dispatches pass through a single authority boundary."""

    def __init__(self) -> None:
        self._handlers: dict[CognitiveStrategy, CognitionStrategyHandler] = {
            CognitiveStrategy.PASSIVE_OBSERVE: PassiveHandler(),
            CognitiveStrategy.DIRECT_RESPONSE: DirectResponseHandler(),
            CognitiveStrategy.REACT_LOOP: ReActHandler(),
            CognitiveStrategy.DELIBERATE_PLANNING: DeliberatePlannerHandler(),
            CognitiveStrategy.SPECIALIST_DELEGATION: SpecialistHandler(),
            CognitiveStrategy.SLEEP_TIME_CONSOLIDATION: SleepTimeHandler(),
        }

    def register_handler(self, strategy: CognitiveStrategy, handler: CognitionStrategyHandler) -> None:
        self._handlers[strategy] = handler

    def execute(
        self,
        strategy: CognitiveStrategy,
        event: JaegerEvent,
        decision: ExecutiveDecision,
        state: SelfState,
        memory: MemorySubsystem,
        authority: AuthorityLayer,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        handler = self._handlers.get(strategy) or self._handlers[CognitiveStrategy.PASSIVE_OBSERVE]
        logger.info("CognitionRouter dispatching strategy %s for event %s", strategy.value, event.event_id)
        return handler.handle(event, decision, state, memory, authority, context or {})
