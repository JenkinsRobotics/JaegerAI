"""
ARES SI — Bridge between the SI pipeline and existing AgenticBackend system.

The SI pipeline produces a ContextBriefing. The bridge:
1. Takes the briefing
2. Composes a prompt from its sections (identity, context, constraints, privacy)
3. Selects the right AgenticBackend via BackendRouter
4. Calls backend.run_turn() with the composed message
5. Returns the result as a WorkerResult

No new adapters. The existing backends ARE the workers.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .types import (
    ContextBriefing,
    ContextItem,
    Constraint,
    MemoryItem,
    SIIdentity,
    WorkerResult,
    DataClassification,
    PrivacyClass,
    PUBLIC,
    PERSONAL,
    PRIVATE,
    SENSITIVE,
    SECRET,
)

logger = logging.getLogger(__name__)

_ENV_SI_ENABLED = "ARES_SI_ENABLED"


def si_enabled() -> bool:
    """Whether the Companion SI pipeline should own chat turns.

    Priority:
    1. ``ARES_SI_ENABLED`` env (1/true/yes/on enables; 0/false/no/off disables)
    2. ``settings.json`` key ``si_enabled`` (bool)
    3. Default: disabled (direct backend path) so tests and plain installs stay
       predictable until production enables SI via launchd or settings.
    """
    raw = os.environ.get(_ENV_SI_ENABLED)
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    try:
        from api.config import load_settings

        settings = load_settings()
        if isinstance(settings, dict) and "si_enabled" in settings:
            return bool(settings.get("si_enabled"))
    except Exception:
        logger.debug("si_enabled settings lookup failed", exc_info=True)
    return False


def compose_prompt_from_briefing(briefing: ContextBriefing, message: str) -> str:
    """Compose a prompt from briefing sections. NOT one monolithic system prompt.

    Each section is separate so workers can't confuse identity with instructions.
    """
    parts: list[str] = []

    # 1. Identity — Companion speaks; workers are tools (do not brand-switch)
    if briefing.si_identity:
        ident = briefing.si_identity
        name = ident.name or "ARES"
        owner = ident.owner_name or "the owner"
        parts.append(
            f"[Identity]\n"
            f"You are {name}, the Companion SI for {owner}. "
            f"You work only for {owner}. "
            f"You are NOT Claude, GPT, Grok, Gemini, Ollama, or any other worker brand. "
            f"Workers execute tools for you; they are not your identity. "
            f"When asked who you are, answer as {name}."
        )
        if ident.mission:
            parts.append(f"[Mission]\n{ident.mission}")
        if ident.principles:
            principles = "\n".join(f"- {p}" for p in ident.principles)
            parts.append(f"[Principles]\n{principles}")
        parts.append(
            f"[Loyalty]\nYour loyalty is to {owner} ({ident.loyalty}). "
            f"Do not claim a different creator, company, or product name as yourself."
        )
    else:
        parts.append(
            "[Identity]\nYou are ARES, a Companion SI. Do not claim to be another agent brand."
        )

    # 2. Context — what the SI knows
    context_items: list[str] = []
    for item in briefing.user_context:
        context_items.append(f"- {item.content}")
    for item in briefing.project_context:
        context_items.append(f"- [Project] {item.content}")
    for mem in briefing.relevant_memories:
        context_items.append(f"- [Memory] {mem.content}")
    if context_items:
        parts.append("[Context]\n" + "\n".join(context_items))

    # 3. Recent conversation
    if briefing.recent_conversation:
        conv_lines = []
        for item in briefing.recent_conversation:
            conv_lines.append(f"- {item.content}")
        parts.append("[Recent conversation]\n" + "\n".join(conv_lines))

    # 4. Constraints — what the worker should/shouldn't do
    constraint_lines: list[str] = [
        "1. [identity] Stay in ARES Companion voice for the full reply.",
        "2. [identity] Never introduce yourself as the underlying model/agent product.",
        "3. [style] Prefer concise, direct answers unless the user asks for depth.",
    ]
    if briefing.constraints:
        for i, c in enumerate(briefing.constraints, 4):
            constraint_lines.append(f"{i}. [{c.kind}] {c.description}")
    parts.append("[Constraints]\n" + "\n".join(constraint_lines))

    # 5. Privacy policy
    if briefing.privacy_policy:
        policy = briefing.privacy_policy
        redacted = policy.get("redacted_types", [])
        if redacted:
            parts.append(f"[Privacy] Do not share {', '.join(redacted)} data outside this conversation.")

    # 6. The user's message
    parts.append(f"[User message]\n{message}")

    return "\n\n".join(parts)


def _worker_to_backend_name(worker_id: str) -> str:
    """Map SI WorkerRecord IDs to existing AgenticBackend names.

    They're already the same: jaeger_local, claude_local, gemini_local, etc.
    """
    return worker_id


def _backend_name_to_privacy_class(backend_name: str) -> PrivacyClass:
    """Infer privacy class from backend name convention."""
    if backend_name.endswith("_local"):
        return PrivacyClass.LOCAL_ONLY
    if backend_name.endswith("_cloud") or backend_name.endswith("_antigravity"):
        return PrivacyClass.APPROVED_PROVIDER
    return PrivacyClass.EXTERNAL_PROVIDER


def si_prepare_message(
    user_message: str,
    *,
    target_worker: str | None = None,
) -> dict[str, Any]:
    """Fast SI packaging only — no worker execution.

    Used by streaming workers (agent stream, etc.) so Companion identity
    can be injected without forcing a non-streaming ``run_turn`` path.
    """
    from .context_compiler import classify_intent, compile_context
    from .trust_engine import classify_data, filter_briefing
    from .router import route_task

    intent, confidence = classify_intent(user_message)
    briefing = compile_context(user_message)
    sensitivity = classify_data(user_message)

    if target_worker:
        backend_name = target_worker
    else:
        routing = route_task(
            intent,
            data_sensitivity=sensitivity.value if sensitivity else "personal",
        )
        selected = routing.get("selected_worker")
        if isinstance(selected, dict):
            backend_name = selected.get("worker_id", "jaeger_local")
        else:
            backend_name = "jaeger_local"

    privacy_class = _backend_name_to_privacy_class(backend_name)
    filtered_briefing = filter_briefing(briefing, privacy_class)
    prompt = compose_prompt_from_briefing(filtered_briefing, user_message)
    return {
        "prompt": prompt,
        "intent": intent,
        "confidence": confidence,
        "worker": backend_name,
        "sensitivity": sensitivity.value if sensitivity else "personal",
        # si_turn needs the identity to compose its final response. Carry the
        # *filtered* briefing's identity so the trust filter is not bypassed —
        # the raw briefing may hold context this worker's privacy class denies.
        "si_identity": filtered_briefing.si_identity,
    }


def si_turn(
    user_message: str,
    session_id: str = "",
    *,
    target_worker: str | None = None,
    model: str = "",
    model_provider: str | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Full SI pipeline: classify → context → route → execute → evaluate → compose.

    This is the main entry point that wires the SI into the existing chat flow.
    When ARES_SI_ENABLED is true, this replaces the direct backend call.
    Prefer streaming workers + :func:`si_prepare_message` when possible so the
    UI is not blocked on a full non-streaming subprocess turn.
    """
    from .evaluator import evaluate_result
    from .response_composer import compose_response
    from api.backends.router import get_router as get_backend_router

    started_at = time.time()

    prepared = si_prepare_message(user_message, target_worker=target_worker)
    intent = prepared["intent"]
    confidence = float(prepared.get("confidence") or 0.0)
    backend_name = str(prepared.get("worker") or "jaeger_local")
    prompt = str(prepared.get("prompt") or user_message)

    # Execute via existing AgenticBackend
    backend_router = get_backend_router()
    backend = backend_router.select(backend_name)

    if backend is None:
        # Fallback to jaeger_local
        backend = backend_router.select("jaeger_local")

    if backend is None:
        return {
            "text": "",
            "error": "No worker is available right now.",
            "intent": intent,
            "worker": None,
            "evaluation": {"verdict": "fail"},
        }

    # 8. Run the turn
    try:
        result = backend.run_turn(
            prompt,
            session_id,
            model=model,
            model_provider=model_provider,
            cancel_event=cancel_event,
            # Companion owns identity — suppress worker SOUL/AGENTS branding.
            si_owned=True,
            ignore_worker_identity=True,
        )
        raw_text = (result or {}).get("text")
        raw_error = (result or {}).get("error")
        # Avoid str(None) → "None", which is truthy and poisons success paths.
        text = "" if raw_text is None else str(raw_text)
        if raw_error is None or raw_error is False:
            error = ""
        else:
            error = str(raw_error).strip()
            if error.lower() in ("none", "null"):
                error = ""
    except Exception as e:
        text = ""
        error = str(e)

    # 9. Evaluate result
    if text:
        evaluation = evaluate_result(text, intent=intent)
        verdict = evaluation.verdict.value if hasattr(evaluation, "verdict") else "unknown"
        checks = [c.check_name for c in evaluation.checks] if hasattr(evaluation, "checks") else []
    else:
        verdict = "fail"
        checks = ["empty_response"]

    # 10. Compose final response
    worker_result = WorkerResult(
        worker_id=backend_name,
        content=text or error,
        confidence=confidence,
    )
    response = compose_response(
        worker_result=worker_result,
        si_identity=prepared.get("si_identity"),
        intent=intent,
        verification={"verdict": verdict, "checks": checks},
        activity_summary=f"Routed to {backend_name} for {intent}",
    )

    duration_ms = int((time.time() - started_at) * 1000)

    return {
        "text": response.content,
        "error": error if error else None,
        "intent": intent,
        "worker": backend_name,
        "evaluation": {"verdict": verdict, "checks": checks},
        "activity_summary": response.activity_summary,
        "warnings": response.warnings,
        "duration_ms": duration_ms,
    }
