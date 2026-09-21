"""Executive Layer & Cognitive Strategy Selection (UPAA Principle 9).

The Executive layer decides the cognitive strategy for an incoming event or
task before dispatching to any model or tool runner.

Strategies:
1. PASSIVE_OBSERVE:
   Salience below threshold or background quiet heartbeat. 0 LLM calls,
   deterministic state reduction only.
2. DIRECT_RESPONSE:
   Conversational, clarifying, or factual query requiring pure model reasoning
   without external tool mutations or deliberate decomposition.
3. REACT_LOOP:
   Single or multi-step tool execution with tool-event consequence feedback.
4. DELIBERATE_PLANNING:
   Complex goal, multi-item batch, or high-risk task requiring an explicit
   work ledger, decomposition into sequential milestones, and verification checks.
5. SPECIALIST_DELEGATION:
   Task explicitly targeted or best suited for a specialized child agent or
   external model provider (e.g. Codex, Hermes, Claude, OpenClaw).
6. SLEEP_TIME_CONSOLIDATION:
   Offline/idle window trigger initiating episodic-to-semantic consolidation,
   skill review, and reflective synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import re
from typing import Any

from .events import EventType, JaegerEvent
from .self_state import SelfState

logger = logging.getLogger("jaeger.entity.executive")


class CognitiveStrategy(str, Enum):
    PASSIVE_OBSERVE = "passive_observe"
    DIRECT_RESPONSE = "direct_response"
    REACT_LOOP = "react_loop"
    DELIBERATE_PLANNING = "deliberate_planning"
    SPECIALIST_DELEGATION = "specialist_delegation"
    SLEEP_TIME_CONSOLIDATION = "sleep_time_consolidation"


# Intent patterns matching deliberate planning / batch requirements
_DELIBERATE_HINTS = re.compile(
    r"(?is)"
    r"(?:do not stop|don't stop|keep going) until|"
    r"(?:process(?:ing)?|consolidat(?:e|ing)|go through|work through)\b.{0,80}?\b(?:all |every |these )?\d{2,}\s+"
    r"(?:items?|files?|rows?|entries|notes?|folders?|records)\b|"
    r"\bbatch[- ](?:process|job|operation|run)\b|"
    r"^/goal\b|"
    r"(?:refactor|rearchitect|migrate)\b.{0,60}?\b(?:subsystem|codebase|repository)\b"
)

# Delegation hints targeting specialists
_DELEGATE_HINTS = re.compile(
    r"(?i)\b(?:delegate|delegat(?:e|ed|ing)|ask|have|let)\s+(?:to\s+)?"
    r"(?:codex|hermes|openclaw|claude|gemini|grok|cursor|opencode)\b"
)

# Tool / Action verbs indicating ReAct loop
_ACTION_HINTS = re.compile(
    r"(?i)\b(?:create|modify|edit|change|update|delete|remove|install|build|"
    r"execute|run|fix|implement|write|move|copy|rename|configure|deploy|"
    r"inspect|review|test|patch|search|find)\b"
)


@dataclass(frozen=True)
class ExecutiveDecision:
    strategy: CognitiveStrategy
    reason: str
    target_specialist: str | None = None
    estimated_steps: int = 1
    requires_work_ledger: bool = False


class ExecutiveStrategySelector:
    """Evaluates events and runtime state to deterministically choose the cognitive strategy."""

    @staticmethod
    def select_strategy(event: JaegerEvent, state: SelfState) -> ExecutiveDecision:
        event_type = event.event_type

        # 1. Heartbeat & Idle Events
        if event_type == EventType.SYSTEM_HEARTBEAT.value:
            quiet = event.payload.get("quiet", True) if isinstance(event.payload, dict) else True
            if quiet:
                return ExecutiveDecision(
                    strategy=CognitiveStrategy.SLEEP_TIME_CONSOLIDATION,
                    reason="Quiet heartbeat trigger indicates idle window suitable for consolidation",
                )
            return ExecutiveDecision(
                strategy=CognitiveStrategy.PASSIVE_OBSERVE,
                reason="Routine heartbeat telemetry; no action needed",
            )

        # 2. Passive / Low Salience Events
        if event.salience < 0.3:
            return ExecutiveDecision(
                strategy=CognitiveStrategy.PASSIVE_OBSERVE,
                reason=f"Event salience {event.salience:.2f} is below observation threshold (0.3)",
            )

        # 3. Human & Bridge Messages
        if event_type == EventType.HUMAN_MESSAGE.value:
            payload = event.payload if isinstance(event.payload, dict) else {}
            text = str(payload.get("text", ""))
            role_s = str(payload.get("role") or event.metadata.get("role") or "")
            exec_mode = str(payload.get("execution_mode") or event.metadata.get("execution_mode") or "")
            actionable = bool(payload.get("actionable") or event.metadata.get("actionable"))

            # Check Delegation / Specialist first
            m_del = _DELEGATE_HINTS.search(text)
            if role_s == "specialist" or m_del or payload.get("specialist"):
                spec = str(payload.get("specialist") or (m_del.group(0).split()[-1].lower() if m_del else role_s))
                return ExecutiveDecision(
                    strategy=CognitiveStrategy.SPECIALIST_DELEGATION,
                    reason=f"Specialist routing for {spec}",
                    target_specialist=spec,
                )

            # Explicit text-only session without actionable request -> DIRECT_RESPONSE
            if exec_mode == "text_only" and not actionable:
                return ExecutiveDecision(
                    strategy=CognitiveStrategy.DIRECT_RESPONSE,
                    reason="Explicit text-only session requested without actionable mutation",
                    estimated_steps=1,
                )

            # Check Deliberate Planning / Batch Work
            if _DELIBERATE_HINTS.search(text) or len(state.active_goals) > 2:
                return ExecutiveDecision(
                    strategy=CognitiveStrategy.DELIBERATE_PLANNING,
                    reason="Detected complex goal or multi-step batch phrasing requiring work ledger",
                    requires_work_ledger=True,
                    estimated_steps=20,
                )

            # In agent mode (or when action hints / actionable intent present), use ReAct Tool Loop
            if (exec_mode and exec_mode != "text_only") or _ACTION_HINTS.search(text) or actionable:
                return ExecutiveDecision(
                    strategy=CognitiveStrategy.REACT_LOOP,
                    reason="Agent mode or actionable request; requires tool dispatch and environment consequence feedback",
                    estimated_steps=5,
                )

            # Direct Response for conversational queries
            return ExecutiveDecision(
                strategy=CognitiveStrategy.DIRECT_RESPONSE,
                reason="Conversational/informational prompt without external mutating tool requirement",
                estimated_steps=1,
            )

        # 4. Perception Events
        if event_type == EventType.PERCEPTION_SENSED.value:
            if event.salience >= 0.7:
                return ExecutiveDecision(
                    strategy=CognitiveStrategy.REACT_LOOP,
                    reason="Salient environmental observation requires proactive tool/action investigation",
                )
            return ExecutiveDecision(
                strategy=CognitiveStrategy.PASSIVE_OBSERVE,
                reason="Routine sensory update absorbed into self-state",
            )

        # Default fallback
        return ExecutiveDecision(
            strategy=CognitiveStrategy.PASSIVE_OBSERVE,
            reason=f"Unhandled event type {event_type}; default to passive observation",
        )
