"""The Canonical Entity Runtime for Jaeger (Pinocchio Architecture).

Implements the single authoritative entity runtime loop:
    EVENT ──► PERSIST ──► UPDATE SELF/WORLD STATE ──► ATTENTION/SALIENCE
                                                          │
                         ┌────────────────────────────────┴────────────────────────┐
                         │                                                         │
               [Salience < Threshold]                                    [Salience >= Threshold]
                         │                                                         │
                   Silent Record                                               Cognition
                  (Zero LLM Calls)                                                 │
                                                                                   ▼
                                                                                 Action
                                                                                   │
                                                                                   ▼
                                                                          Observe Consequence
                                                                                   │
                                                                                   ▼
                                                                           Consequence Event
                                                                                   │
                                                                                   ▼
                                                                            Memory / Learning
"""

from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable

from jaeger_ai.core.instance.instance import operator_state_root
from .ownership import EntityRuntimeMode, infer_runtime_mode, instance_layout, runtime_state_root
from .attention import AttentionDecision, SalienceEngine
from .authority import AuthorityDecision, AuthorityLayer, ProposedAction
from .cognition_router import CognitionRouter
from .deliberate_planner import DeliberatePlanner
from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .executive import CognitiveStrategy, ExecutiveDecision, ExecutiveStrategySelector
from .identity import EntityIdentity, resolve_entity_identity  # load_from_file used in ATTACHED_CLIENT
from .learning import LearningDecision, LearningPipeline
from .memory import MemorySubsystem
from .reducer import reduce_event, replay_events
from .reflection import ReflexionStore
from .self_refine import SelfRefineEngine
from .self_state import SelfState
from .sleep_time import SleepTimeProcessor
from .verification import (
    VerificationContract,
    VerificationRegistry,
    VerificationResult,
    VerificationStatus,
)

logger = logging.getLogger("jaeger.entity.runtime")


class EntityRuntime:
    """The persistent sovereign entity runtime."""

    _instance: EntityRuntime | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        state_root: Path | str | None = None,
        identity: EntityIdentity | None = None,
        event_store: SqliteEventStore | None = None,
        salience_engine: SalienceEngine | None = None,
        mode: EntityRuntimeMode | None = None,
    ) -> None:
        self.mode = mode or infer_runtime_mode()
        try:
            self.layout = instance_layout()
        except Exception:
            self.layout = None
        if state_root is not None:
            self.state_root = Path(state_root)
        elif self.layout is not None:
            self.state_root = runtime_state_root()
        else:
            self.state_root = operator_state_root()
        self.state_root.mkdir(parents=True, exist_ok=True)

        identity_root = self.state_root
        if self.mode == EntityRuntimeMode.ATTACHED_CLIENT:
            ident_path = identity_root / "entity_identity.json"
            if ident_path.is_file():
                self.identity = identity or EntityIdentity.load_from_file(ident_path)
            else:
                self.identity = identity or resolve_entity_identity(identity_root)
        else:
            self.identity = identity or resolve_entity_identity(self.state_root)
        event_path = self.state_root / "entity_events.sqlite3"
        if self.layout is not None and state_root is None:
            event_path = self.layout.event_store_path
        self.event_store = event_store or SqliteEventStore(event_path)
        self.salience_engine = salience_engine or SalienceEngine()
        self.executive_selector = ExecutiveStrategySelector()
        self.authority_layer = AuthorityLayer()
        self.verification_registry = VerificationRegistry()
        self.verification_contract = VerificationContract()
        self.memory_subsystem = MemorySubsystem(self.state_root, self.event_store)
        self.reflexion_store = ReflexionStore(self.state_root)
        self.learning_pipeline = LearningPipeline(
            self.state_root,
            self.event_store,
            self.memory_subsystem,
            self.verification_contract,
        )
        self.deliberate_planner = DeliberatePlanner()
        self.self_refine_engine = SelfRefineEngine()
        self.sleep_time_processor = SleepTimeProcessor(
            self.state_root,
            self.event_store,
            self.memory_subsystem,
        )
        self.cognition_router = CognitionRouter()
        from jaeger_ai.core.context_compiler import ContextCompiler
        self.context_compiler = ContextCompiler()
        from jaeger_ai.core.diagnostics.unified_trace import SqliteTraceStore
        self.trace_store = SqliteTraceStore(self.state_root / "execution_traces.sqlite3")
        try:

            from .resident import try_become_resident
            if self.mode == EntityRuntimeMode.OWNER:
                lock_root = self.layout.run_dir if self.layout is not None else self.state_root
                self.is_resident = try_become_resident(lock_root)
            elif self.mode == EntityRuntimeMode.TEST:
                self.is_resident = try_become_resident(self.state_root)
            else:
                self.is_resident = False
        except Exception:
            self.is_resident = False
        # RecoveryManager may call get_singleton(); never scan while the
        # constructor still holds the singleton lock.

        # Reconstruct initial state from cold boot replay
        base_state = SelfState(
            identity=self.identity,
            boot_timestamp=time.time(),
        )
        self._state = replay_events(base_state, self.event_store.replay_all())
        self._state_lock = threading.RLock()
        self._cognition_handlers: list[Callable[[JaegerEvent, SelfState], Any]] = []

        logger.info(
            "Initialized EntityRuntime for %s (%s) with %d replayed events",
            self.identity.display_name,
            self.identity.entity_id,
            self._state.total_events_processed,
        )

    @classmethod
    def get_singleton(cls, state_root: Path | str | None = None, *, mode: EntityRuntimeMode | None = None) -> EntityRuntime:
        """Process-wide singleton instance of the EntityRuntime."""
        created = False
        with cls._lock:
            if cls._instance is None:
                resolved_mode = mode or infer_runtime_mode()
                cls._instance = cls(state_root=state_root, mode=resolved_mode)
                created = True
            instance = cls._instance
        if created and instance.mode == EntityRuntimeMode.OWNER and instance.is_resident:
            try:
                from .recovery import RecoveryManager
                instance._recovery_report = RecoveryManager().scan_resumable_runs()
            except Exception:
                instance._recovery_report = None
        return instance

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset singleton reference (for test isolation)."""
        with cls._lock:
            cls._instance = None

    @property
    def current_state(self) -> SelfState:
        with self._state_lock:
            return self._state

    def register_cognition_handler(
        self, handler: Callable[[JaegerEvent, SelfState], Any]
    ) -> None:
        """Register a handler to be invoked when an event triggers cognition wake."""
        self._cognition_handlers.append(handler)

    def ingest(self, event: JaegerEvent) -> tuple[SelfState, AttentionDecision]:
        """Core Invariant Execution Loop:

        1. PERSIST event durably to event store.
        2. UPDATE SelfState deterministically via reducer.
        3. EVALUATE Attention/Salience.
        4. WAKE cognition if required.
        """
        # 1. Persist
        persisted = self.event_store.append(event)
        is_duplicate = (persisted.event_id != event.event_id)

        # 2. Update SelfState only on new event
        with self._state_lock:
            if not is_duplicate:
                self._state = reduce_event(self._state, persisted)
            current_state = self._state

        # 3. Attention / Salience Evaluation
        decision = self.salience_engine.evaluate(persisted, current_state)

        # 4. Trigger cognition handlers if salient and new
        if decision.wake_cognition and not is_duplicate:
            for handler in self._cognition_handlers:
                try:
                    handler(persisted, current_state)
                except Exception as exc:
                    logger.error("Cognition handler failed for event %s: %s", persisted.event_id, exc)

        return current_state, decision

    def execute_turn(
        self,
        user_text: str,
        *,
        session_id: str = "dispatcher",
        source: str = "chat",
        actor: str = "human:operator",
        request_id: str | None = None,
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a turn through the sovereign UPAA control path:
        EVENT
        -> EVENT FABRIC
        -> PERSIST
        -> PERCEPTION / STATE REDUCTION
        -> SELF STATE UPDATE
        -> ATTENTION / SALIENCE
        -> EXECUTIVE STRATEGY SELECTION
        -> COGNITION MODE & PROVIDER
        -> PROPOSED ACTION / AUTHORITY
        -> ACTION SYSTEM / ENVIRONMENT
        -> CONSEQUENCE EVENT
        -> VERIFICATION
        -> LEARNING
        -> MEMORY UPDATE
        """
        ctx = dict(context or {})
        meta = dict(metadata or {})
        if "metadata" in ctx and isinstance(ctx["metadata"], dict):
            meta.update(ctx["metadata"])

        # 1. Ingest event to Fabric, reduce SelfState, evaluate Salience
        trace_id = str(meta.get("trace_id") or request_id or f"T{int(time.time()*1000)}")
        meta["trace_id"] = trace_id
        from jaeger_ai.core.diagnostics.unified_trace import ExecutionTrace
        unified_trace = ExecutionTrace(
            trace_id=f"tr_{trace_id}" if not trace_id.startswith("tr_") else trace_id,
            request_id=request_id or trace_id,
            session_id=session_id,
            actor=actor,
            goal=user_text,
        )
        unified_trace.start_span("attention")
        event = JaegerEvent.human_message(
            user_text,
            actor=actor,
            source=source,
            session_id=session_id,
            request_id=request_id,
            metadata=meta,
        )
        current_state, attention = self.ingest(event)
        if unified_trace.spans:
            unified_trace.spans[-1].finish(extra_data={"salience": getattr(attention, "salience_score", None)})

        try:
            import re as _re
            for token in _re.findall(
                r"(?i)\bremember(?:\s+(?:the\s+)?(?:word|token|code|phrase))?\s+[\"']?([A-Za-z][A-Za-z0-9_-]{1,48})",
                user_text,
            ):
                self.memory_subsystem.semantic.record_claim(
                    "user",
                    "remembered_word",
                    token,
                    source_id=event.event_id,
                    confidence=0.95,
                )
        except Exception:
            pass
        try:
            recall_lines = ["# Durable fabric (not a new conversation):"]
            for claim in self.memory_subsystem.semantic.list_recent(12):
                recall_lines.append(
                    f"- claim {claim.get('subject')}.{claim.get('predicate')}={claim.get('value')}"
                )
            recent = self.event_store.query_events(
                event_types=[EventType.HUMAN_MESSAGE.value, EventType.AGENT_RESPONSE.value],
                since_id=max(0, self.event_store.latest_id() - 400),
                limit=400,
            )[-12:]
            for ev in recent:
                text = str((ev.payload or {}).get("text") or "")[:240]
                if text:
                    recall_lines.append(f"- {ev.event_type}: {text}")
            if len(recall_lines) > 1:
                ctx["durable_recall"] = "\n".join(recall_lines)
        except Exception:
            pass
        try:
            from jaeger_ai.core.runtime.truth import capability_prompt_block
            ctx["runtime_truth"] = capability_prompt_block(
                self.layout.root if getattr(self, "layout", None) else None
            )
        except Exception:
            pass

        # Passive gate: if salience indicates no wake
        if not attention.wake_cognition:
            return {
                "text": "",
                "error": None,
                "tool_activity": [],
                "report": {},
                "skipped_final": False,
                "strategy": CognitiveStrategy.PASSIVE_OBSERVE.value,
                "wake_cognition": False,
            }

        # 2. Executive Strategy Selection
        try:
            refs = self.reflexion_store.retrieve_applicable(user_text)
            if refs:
                meta["reflection_count"] = len(refs)
                event.payload["reflection_count"] = len(refs)
                self.event_store.append(
                    JaegerEvent.typed(
                        EventType.REFLECTION_RETRIEVED.value,
                        {
                            "count": len(refs),
                            "ids": [r.reflection_id for r in refs],
                        },
                        actor="system:reflexion",
                        source="reflexion_store",
                        parent_event_id=event.event_id,
                        session_id=session_id,
                    )
                )
        except Exception:
            pass
        try:
            pipeline = getattr(self.sleep_time_processor, "skill_pipeline", None)
            matched_skills = pipeline.matching_skills(user_text) if pipeline is not None else []
            if matched_skills:
                lines = ["# Learned skills (follow these verified procedures):"]
                for rec in matched_skills:
                    name = str(rec.get("name") or "skill")
                    desc = str(rec.get("description") or "")
                    lines.append(f"- {name}: {desc}".rstrip(": "))
                    self.event_store.append(
                        JaegerEvent.typed(
                            EventType.SKILL_USED.value,
                            {"skill_name": name, "description": desc},
                            actor="agent:skill_registry",
                            source="skills.promotion",
                            parent_event_id=event.event_id,
                            session_id=session_id,
                        )
                    )
                ctx["learned_skills_prompt"] = "\n".join(lines)
        except Exception:
            pass
        unified_trace.start_span("executive")
        exec_decision = self.executive_selector.select_strategy(event, current_state)
        if unified_trace.spans:
            unified_trace.spans[-1].finish(extra_data={"strategy": exec_decision.strategy.value, "reason": exec_decision.reason})
        unified_trace.strategy = exec_decision.strategy.value
        self.event_store.append(
            JaegerEvent.executive_decision(
                exec_decision.strategy.value,
                exec_decision.reason,
                parent_event_id=event.event_id,
                session_id=session_id,
            )
        )

        # 3. Cognition Router Execution
        if self.layout is not None:
            ctx.setdefault("workspace", str(self.layout.workspace_dir))
            ctx.setdefault("instance_root", str(self.layout.root))
            ctx.setdefault("layout", self.layout)
        try:
            from .indexing import IndexCoordinator
            hits = IndexCoordinator(self.state_root, event_store=self.event_store).retrieve(user_text, limit=4)
            if hits:
                lines = ["# Retrieved documents (not semantic facts; provenance=RETRIEVED_DOCUMENT):"]
                for hit in hits:
                    src = str(hit.get("source_id") or hit.get("path") or "")
                    snippet = str(hit.get("text") or "")[:400]
                    lines.append(f"- {src}: {snippet}")
                ctx["retrieved_documents"] = "\n".join(lines)
                self.event_store.append(
                    JaegerEvent.typed(
                        EventType.SYSTEM_OBSERVATION.value,
                        {
                            "kind": "retrieved_document",
                            "provenance": "RETRIEVED_DOCUMENT",
                            "query": user_text[:240],
                            "hits": [
                                {
                                    "source_id": h.get("source_id"),
                                    "provenance": "RETRIEVED_DOCUMENT",
                                    "text": str(h.get("text") or "")[:240],
                                }
                                for h in hits
                            ],
                        },
                        actor="system:indexer",
                        source="indexing.retrieve",
                        parent_event_id=event.event_id,
                        session_id=session_id,
                    )
                )
        except Exception:
            pass
        ctx["sleep_processor"] = self.sleep_time_processor
        ctx["reflexion_store"] = self.reflexion_store
        if "cognition_provider" not in ctx and callable(ctx.get("model_runner")):
            ctx["cognition_provider"] = ctx["model_runner"]
        if "critic_provider" not in ctx and callable(ctx.get("model_runner")):
            ctx["critic_provider"] = ctx["model_runner"]
        try:
            raw_claims = list(self.memory_subsystem.semantic.list_recent(12))
        except Exception:
            raw_claims = []
        try:
            compiled = self.context_compiler.compile(
                user_text,
                identity=self.identity,
                self_state=current_state,
                runtime_truth=ctx.get("runtime_truth"),
                claims=raw_claims,
                events=recent if 'recent' in locals() else [],
                reflections=refs if 'refs' in locals() else [],
                documents=hits if 'hits' in locals() else [],
                skills=matched_skills if 'matched_skills' in locals() else [],
                budget_tokens=ctx.get("budget_tokens") or 4096,
            )
            ctx["compiled_context"] = compiled
            ctx["system_prompt"] = compiled.system_prompt
        except Exception as exc:
            logger.debug("Context compilation skipped/failed: %s", exc)

        unified_trace.start_span("cognition")
        ctx["parent_event_id"] = event.event_id
        ctx["session_id"] = session_id
        ctx["event_store"] = self.event_store
        cog_result = self.cognition_router.execute(
            strategy=exec_decision.strategy,
            event=event,
            decision=exec_decision,
            state=current_state,
            memory=self.memory_subsystem,
            authority=self.authority_layer,
            context=ctx,
        )
        if unified_trace.spans:
            unified_trace.spans[-1].finish()
        unified_trace.model = str(ctx.get("model") or getattr(self.cognition_router, "default_model", None) or "")
        unified_trace.provider = str(ctx.get("provider") or getattr(self.cognition_router, "default_provider", None) or "")

        response_text = str((cog_result or {}).get("text") or "")

        if getattr(exec_decision, "refinement_required", False) and (response_text or user_text):
            try:
                critic_p = ctx.get("critic_provider")
                cognition_p = ctx.get("cognition_provider")
                draft = response_text or ""
                if callable(cognition_p) and len(draft.strip()) < 400:
                    try:
                        drafted = cognition_p(
                            "Produce a complete technical artifact as markdown. "
                            "Include rollback, verification, and failure recovery. "
                            "No tools. Objective:\n" + user_text
                        )
                        if str(drafted or "").strip():
                            draft = str(drafted)
                    except Exception as exc:
                        logger.debug("Self-refine draft generation skipped: %s", exc)
                self.event_store.append(
                    JaegerEvent.typed(
                        EventType.ARTIFACT_GENERATED.value,
                        {"chars": len(draft)},
                        actor="agent:cognition",
                        source="self_refine",
                        parent_event_id=event.event_id,
                        session_id=session_id,
                    )
                )
                refinement = self.self_refine_engine.refine_artifact(
                    draft or user_text,
                    rubric="Completeness, rollback, verification, failure handling, safety",
                    critic_provider=critic_p if callable(critic_p) else None,
                    cognition_provider=cognition_p if callable(cognition_p) else None,
                    max_iterations=2,
                )
                self.event_store.append(
                    JaegerEvent.typed(
                        EventType.ARTIFACT_CRITIQUED.value,
                        {
                            "iterations": refinement.iterations,
                            "approved": refinement.is_approved,
                            "critic": "provider" if callable(critic_p) or callable(cognition_p) else "default",
                        },
                        actor="agent:critic",
                        source="self_refine",
                        parent_event_id=event.event_id,
                        session_id=session_id,
                    )
                )
                if refinement.refined and refinement.refined != draft:
                    response_text = refinement.refined
                    if isinstance(cog_result, dict):
                        cog_result = dict(cog_result)
                        cog_result["text"] = response_text
                    self.event_store.append(
                        JaegerEvent.typed(
                            EventType.ARTIFACT_REVISED.value,
                            {"chars": len(response_text)},
                            actor="agent:cognition",
                            source="self_refine",
                            parent_event_id=event.event_id,
                            session_id=session_id,
                        )
                    )
                self.event_store.append(
                    JaegerEvent.typed(
                        EventType.ARTIFACT_VALIDATED.value,
                        {"approved": refinement.is_approved},
                        actor="system:validator",
                        source="self_refine",
                        parent_event_id=event.event_id,
                        session_id=session_id,
                    )
                )
            except Exception as exc:
                logger.debug("Self-refine skipped: %s", exc)

        # 4. Action-Specific Independent Verification
        from .verification import derive_verification_action

        if self.layout is not None:
            ctx.setdefault("workspace", str(self.layout.workspace_dir))
            ctx.setdefault("instance_root", str(self.layout.root))
            ctx.setdefault("layout", self.layout)
        try:
            before_id = max(0, self.event_store.latest_id() - 800)
        except Exception:
            before_id = 0
        turn_tools = self.event_store.query_events(
            event_types=[
                EventType.TOOL_STARTED.value,
                EventType.TOOL_COMPLETED.value,
                EventType.TOOL_FAILED.value,
            ],
            since_id=before_id,
            limit=800,
        )
        if event.timestamp:
            turn_tools = [
                e for e in turn_tools
                if float(getattr(e, "timestamp", 0) or 0) >= event.timestamp - 0.05
            ]
        action = (cog_result or {}).get("action") if isinstance(cog_result, dict) else None
        if not isinstance(action, dict) or not action.get("action_type"):
            action = derive_verification_action(
                user_text,
                cog_result or {},
                turn_tools,
                strategy=exec_decision.strategy.value,
                context=ctx,
            )

        verif = self.verification_registry.verify(
            objective=user_text,
            action=action,
            result=cog_result or {},
            context=ctx,
        )
        failed_tools = [
            e for e in turn_tools
            if e.event_type == EventType.TOOL_FAILED.value
        ]
        if (
            failed_tools
            and verif.status == VerificationStatus.OBJECTIVE_VERIFIED
            and str(action.get("action_type") or "") in {"unknown", "read_only", ""}
        ):
            failed_payload = failed_tools[-1].payload or {}
            err = str(failed_payload.get("error") or "tool failed")
            failed_tool = str(failed_payload.get("tool") or failed_payload.get("tool_name") or "tool")
            verif = VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=user_text,
                evidence=f"Tool failure ({failed_tool}): {err}",
                verifier="tool_failure_override",
                error=err,
            )

        tool_ids = [str(getattr(e, "event_id", "") or "") for e in turn_tools if getattr(e, "event_id", "")]
        unified_trace.verification = {"status": verif.status.value, "verifier": verif.verifier, "error": verif.error}
        verif_ev = JaegerEvent.verification_completed(
            objective=user_text,
            status=verif.status.value,
            evidence=verif.evidence,
            verifier=verif.verifier,
            error=verif.error,
            parent_event_id=event.event_id,
            session_id=session_id,
            extra={
                "target": (action or {}).get("path") or (action or {}).get("target_path"),
                "action_type": (action or {}).get("action_type"),
                "tool_event_ids": tool_ids,
                "request_id": request_id,
                "trace_id": trace_id,
            },
        )
        self.event_store.append(verif_ev)

        # 5. Continuous Learning & Memory Update
        self.learning_pipeline.record_turn_experience(
            event=event,
            decision=exec_decision,
            cog_result=cog_result or {},
            verification=verif,
            reflexion_store=self.reflexion_store,
            state=current_state,
        )
        self.event_store.append(
            JaegerEvent.learning_updated(
                learning_type="turn_experience",
                summary=f"Turn experience recorded for {exec_decision.strategy.value} (verif: {verif.status.value})",
                parent_event_id=verif_ev.event_id,
                session_id=session_id,
            )
        )

        # 6. Record Agent Response in Event Fabric
        if response_text:
            self.record_agent_response(
                response_text,
                session_id=session_id,
                parent_event_id=event.event_id,
                metadata={
                    "strategy": exec_decision.strategy.value,
                    "plan_id": (cog_result or {}).get("plan_id"),
                    "user_text": user_text,
                    "agent_response": response_text,
                    "tool_calls": (cog_result or {}).get("tool_activity") or [],
                },
            )

        # Standard dictionary format for callers
        result_dict = dict(cog_result or {})
        if "tool_activity" not in result_dict:
            result_dict["tool_activity"] = []
        if "error" not in result_dict:
            result_dict["error"] = None
        if "report" not in result_dict:
            result_dict["report"] = {}
        if "skipped_final" not in result_dict:
            result_dict["skipped_final"] = False
        result_dict["strategy"] = exec_decision.strategy.value
        result_dict["text"] = response_text
        result_dict["verification"] = {
            "status": verif.status.value,
            "verifier": verif.verifier,
            "evidence": verif.evidence,
            "event_id": verif_ev.event_id,
        }

        turn_err = result_dict.get("error")
        unified_trace.tool_calls = list(result_dict.get("tool_activity") or [])
        unified_trace.finish(
            status="failed" if turn_err else "success",
            error=turn_err,
        )
        try:
            self.trace_store.save_trace(unified_trace)
        except Exception as exc:
            logger.debug("Failed saving trace: %s", exc)
        result_dict["trace_id"] = unified_trace.trace_id

        return result_dict

    def run_subordinate_react(
        self,
        prompt: str,
        *,
        session_key: str = "dispatcher",
        request_id: str | None = None,
        confirmation_provider: Any = None,
        native_run_id: str | None = None,
        max_iterations: int = 12,
        max_tool_calls: int = 8,
        on_run: Callable[[str], None] | None = None,
    ) -> str:
        """Execute subordinate ReAct loop inside the EntityRuntime.

        Provides canonical execution of tool-using ReAct cognition owned
        by the EntityRuntime, ensuring consistent permission policies,
        turn commitments, and execution tracking across all clients.
        """
        import os
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        from jaeger_ai.core.models.external_model import ExternalModelClient
        from jaeger_agent.cognition.executive import TurnExecutive
        from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
        from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
        from jaeger_agent.loop.runtime_bridge import build_jaeger_agent
        from jaeger_agent.memory import sqlite_store

        layout = self.layout
        if layout is None:
            raise RuntimeError("OWNER layout missing; cannot run in-process ReAct")
        sqlite_store.bind(layout)
        try:
            from jaeger_agent.workspace import bind as bind_workspace
            bind_workspace(layout)
        except Exception:
            pass

        if confirmation_provider is not None:
            try:
                from jaeger_os.core.safety.permissions import PermissionPolicy, PolicyMode, install_policy
                install_policy(PermissionPolicy(
                    mode=PolicyMode.NORMAL,
                    confirmation=confirmation_provider,
                ))
            except Exception:
                try:
                    from jaeger_ai.core.instance.commissioning import install_commissioning_permissions
                    install_commissioning_permissions(layout)
                except Exception:
                    pass
        else:
            try:
                from jaeger_ai.core.instance.commissioning import install_commissioning_permissions
                install_commissioning_permissions(layout)
            except Exception:
                pass

        cfg = load_yaml(layout.config_path, Config)
        client = ExternalModelClient(cfg.external_model, layout)
        agent = build_jaeger_agent(client, max_iterations=max_iterations, max_tool_calls=max_tool_calls)
        if native_run_id:
            try:
                agent.bind_run(native_run_id)
            except Exception:
                pass
        turn_exec = TurnExecutive(
            agent,
            SqliteRunStore(),
            SqliteCommitmentStore(),
            provider=str(cfg.external_model.provider or "ollama"),
        )
        os.environ.setdefault("JAEGER_ACCEPT_HOOKS", "1")
        run = turn_exec.ensure_run()
        if on_run is not None:
            # Before any effect: a crash from here on must be attributable
            # to this run, or recovery cannot tell done work from undone.
            on_run(run.id)
        out = turn_exec.run_turn(prompt)
        out = (out or "").strip()
        return out if out else "(No response text returned)"

    @staticmethod
    def run_has_indeterminate_effects(run_id: str) -> bool:
        """True when ``run_id`` claimed an effect it never resolved.

        Fails closed: if the ledger cannot be read, the outcome is unknown.
        """
        try:
            from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
            return any(e.run_id == run_id for e in SqliteEffectLedger().list(status="pending"))
        except Exception:
            logger.warning("effect ledger unreadable for run %s; treating as indeterminate", run_id)
            return True

    def subordinate_model_name(self) -> str:
        """The model :meth:`run_subordinate_react` calls, as its provider names it."""
        from jaeger_ai.core.instance.schemas import Config, load_yaml

        if self.layout is None:
            return ""
        external = load_yaml(self.layout.config_path, Config).external_model
        return f"{external.provider}:{external.model}" if external.enabled else "local"

    # ── Specialized Ingress Helpers ───────────────────────────────────

    def submit_human_message(
        self,
        text: str,
        *,
        actor: str = "human:operator",
        source: str = "chat",
        session_id: str = "dispatcher",
        request_id: str | None = None,
    ) -> tuple[JaegerEvent, AttentionDecision]:
        event = JaegerEvent.human_message(
            text,
            actor=actor,
            source=source,
            session_id=session_id,
            request_id=request_id,
        )
        _, decision = self.ingest(event)
        return event, decision

    def submit_heartbeat(
        self,
        *,
        source: str = "runtime.heartbeat",
        payload: dict[str, Any] | None = None,
    ) -> tuple[JaegerEvent, AttentionDecision]:
        event = JaegerEvent.heartbeat(source=source, payload=payload)
        _, decision = self.ingest(event)
        return event, decision

    def submit_observation(
        self,
        sensor: str,
        signals: dict[str, Any],
        *,
        salience: float = 0.2,
        session_id: str = "system",
    ) -> tuple[JaegerEvent, AttentionDecision]:
        event = JaegerEvent.perception_sensed(
            sensor,
            signals,
            salience=salience,
            session_id=session_id,
        )
        _, decision = self.ingest(event)
        return event, decision

    def record_tool_start(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str,
        session_id: str = "dispatcher",
        actor: str = "agent:jaeger",
        parent_event_id: str = "",
    ) -> JaegerEvent:
        event = JaegerEvent.tool_started(
            tool_name,
            arguments,
            call_id=call_id,
            session_id=session_id,
            actor=actor,
            parent_event_id=parent_event_id,
        )
        self.ingest(event)
        return event

    def record_tool_result(
        self,
        tool_name: str,
        result: Any,
        *,
        call_id: str,
        duration_s: float,
        session_id: str = "dispatcher",
        error: str | None = None,
        parent_event_id: str = "",
    ) -> JaegerEvent:
        if error:
            event = JaegerEvent.tool_failed(
                tool_name,
                error,
                call_id=call_id,
                duration_s=duration_s,
                session_id=session_id,
                parent_event_id=parent_event_id,
            )
        else:
            event = JaegerEvent.tool_completed(
                tool_name,
                result,
                call_id=call_id,
                duration_s=duration_s,
                session_id=session_id,
                parent_event_id=parent_event_id,
            )
        self.ingest(event)
        return event

    def record_agent_response(
        self,
        text: str,
        *,
        session_id: str = "dispatcher",
        actor: str = "agent:jaeger",
        model: str = "",
        metadata: dict[str, Any] | None = None,
        parent_event_id: str = "",
    ) -> JaegerEvent:
        event = JaegerEvent(
            event_id="",
            event_type=EventType.AGENT_RESPONSE.value,
            actor=actor,
            source="runtime.cognition",
            timestamp=time.time(),
            session_id=session_id,
            payload={"text": text, "model": model, **(metadata or {})},
            salience=0.5,
            parent_event_id=parent_event_id,
        )
        self.ingest(event)
        return event

    def record_background_completed(
        self,
        task_id: str,
        result: Any,
        *,
        session_id: str = "dispatcher",
        error: str | None = None,
        requires_followup: bool = False,
    ) -> JaegerEvent:
        event = JaegerEvent(
            event_id="",
            event_type=EventType.BACKGROUND_COMPLETED.value,
            actor="system:background",
            source="runtime.background",
            timestamp=time.time(),
            session_id=session_id,
            payload={
                "task_id": task_id,
                "source_session": session_id,
                "originating_event_id": str((result or {}).get("originating_event_id") or "") if isinstance(result, dict) else "",
                "status": "failed" if error else "completed",
                "result_summary": str((result or {}).get("summary") or result)[:500] if result is not None else (error or ""),
                "artifact_refs": list((result or {}).get("artifact_refs") or []) if isinstance(result, dict) else [],
                "result": result,
                "error": error,
                "requires_followup": requires_followup,
            },
            salience=0.7 if requires_followup else 0.3,
        )
        self.ingest(event)
        return event
