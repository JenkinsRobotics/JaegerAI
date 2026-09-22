"""Context Compiler (Workstream 6).

Separates durable memory from model context via the canonical pipeline:
SELECT
→ RANK
→ BUDGET
→ PROVENANCE
→ FORMAT FOR COGNITION PROFILE

Invariants:
- Context is a projection of durable state; prompts are never the storage layer.
- Context budgets are measurable and auditable before model dispatch.
- Every admitted memory fragment carries structured provenance.
- Lower-priority memories are gracefully dropped when budgets are constrained.
"""
from __future__ import annotations

import math
from typing import Any, Mapping
from .models import ContextItem, CompiledContext
from .provenance import MemoryProvenance


class ContextCompiler:
    """Canonical Context Compiler for Jaeger persistent cognition."""

    # Default estimation heuristic: ~3.6 characters per token for English & code
    CHARS_PER_TOKEN = 3.6

    def __init__(self, default_budget_tokens: int = 4096) -> None:
        self.default_budget_tokens = default_budget_tokens

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.CHARS_PER_TOKEN))

    def select(
        self,
        goal: str,
        *,
        identity: Any = None,
        self_state: Any = None,
        runtime_truth: str | None = None,
        claims: list[dict[str, Any]] | None = None,
        events: list[Any] | None = None,
        reflections: list[Any] | None = None,
        documents: list[dict[str, Any]] | None = None,
        skills: list[dict[str, Any]] | None = None,
        observations: list[dict[str, Any]] | None = None,
    ) -> list[ContextItem]:
        """Step 1: SELECT candidate items from disparate memory and knowledge subsystems."""
        items: list[ContextItem] = []

        # 1. Identity (Priority 0 - Highest / Essential)
        if identity is not None:
            name = getattr(identity, "display_name", "Jaeger")
            eid = getattr(identity, "entity_id", "jaeger-entity")
            role = getattr(identity, "system_role", "Persistent cognitive assistant")
            content = f"Identity: {name} (ID: {eid})\nRole: {role}"
            items.append(ContextItem(
                item_id=f"identity_{eid}",
                provenance=MemoryProvenance.IDENTITY,
                content=content,
                salience=1.0,
                priority=0,
                tokens_estimate=self.estimate_tokens(content),
            ))

        # 2. Runtime Truth / Capabilities (Priority 1)
        if runtime_truth:
            items.append(ContextItem(
                item_id="runtime_truth",
                provenance=MemoryProvenance.RUNTIME_TRUTH,
                content=f"[Runtime Capabilities & Verification Truth]\n{runtime_truth.strip()}",
                salience=0.95,
                priority=1,
                tokens_estimate=self.estimate_tokens(runtime_truth),
            ))

        # 3. Self State (Priority 2)
        if self_state is not None:
            mood = getattr(self_state, "mood", "neutral")
            energy = getattr(self_state, "energy", 1.0)
            events_proc = getattr(self_state, "total_events_processed", 0)
            content = f"Current Self State: mood={mood}, energy={energy:.2f}, total_events={events_proc}"
            items.append(ContextItem(
                item_id="self_state",
                provenance=MemoryProvenance.SELF_STATE,
                content=content,
                salience=0.8,
                priority=2,
                tokens_estimate=self.estimate_tokens(content),
            ))

        # 4. Learned Skills (Priority 3)
        if skills:
            for idx, s in enumerate(skills):
                s_name = str(s.get("name") or f"skill_{idx}")
                s_desc = str(s.get("description") or "")
                content = f"Skill [{s_name}]: {s_desc}"
                items.append(ContextItem(
                    item_id=f"skill_{s_name}",
                    provenance=MemoryProvenance.LEARNED_SKILL,
                    content=content,
                    salience=float(s.get("score") or 0.8),
                    priority=3,
                    tokens_estimate=self.estimate_tokens(content),
                ))

        # 5. Reflections (Priority 4)
        if reflections:
            for idx, r in enumerate(reflections):
                critique = getattr(r, "critique", None) or (r.get("critique") if isinstance(r, dict) else str(r))
                content = f"Prior Reflection: {critique}"
                items.append(ContextItem(
                    item_id=f"reflection_{idx}",
                    provenance=MemoryProvenance.REFLEXION,
                    content=content,
                    salience=0.75,
                    priority=4,
                    tokens_estimate=self.estimate_tokens(content),
                ))

        # 6. Semantic Claims (Priority 5)
        if claims:
            for idx, c in enumerate(claims):
                subj = c.get("subject", "user")
                pred = c.get("predicate", "attribute")
                val = c.get("value", "")
                conf = float(c.get("confidence") or 0.9)
                content = f"Fact: {subj}.{pred} = {val} (confidence={conf:.2f})"
                items.append(ContextItem(
                    item_id=f"claim_{idx}",
                    provenance=MemoryProvenance.SEMANTIC_CLAIM,
                    content=content,
                    salience=conf,
                    priority=5,
                    tokens_estimate=self.estimate_tokens(content),
                ))

        # 7. Retrieved Documents (Priority 6)
        if documents:
            for idx, d in enumerate(documents):
                src = d.get("source_id") or d.get("path") or f"doc_{idx}"
                snippet = str(d.get("text") or "")[:400]
                content = f"Retrieved Document [{src}]:\n{snippet}"
                items.append(ContextItem(
                    item_id=f"doc_{idx}",
                    provenance=MemoryProvenance.RETRIEVED_DOCUMENT,
                    content=content,
                    salience=float(d.get("score") or 0.6),
                    priority=6,
                    tokens_estimate=self.estimate_tokens(content),
                ))

        # 8. Device Observations (Priority 7)
        if observations:
            for idx, obs in enumerate(observations):
                sensor = obs.get("sensor", "device")
                signals = str(obs.get("signals") or "")[:200]
                content = f"Observation [{sensor}]: {signals}"
                items.append(ContextItem(
                    item_id=f"obs_{idx}",
                    provenance=MemoryProvenance.DEVICE_OBSERVATION,
                    content=content,
                    salience=float(obs.get("salience") or 0.4),
                    priority=7,
                    tokens_estimate=self.estimate_tokens(content),
                ))

        # 9. Recent Events (Priority 8)
        if events:
            for idx, ev in enumerate(events):
                ev_type = getattr(ev, "event_type", "event")
                payload = getattr(ev, "payload", {}) or {}
                txt = str(payload.get("text") or payload.get("output") or "")[:200]
                if txt:
                    content = f"Recent Event [{ev_type}]: {txt}"
                    items.append(ContextItem(
                        item_id=f"ev_{idx}",
                        provenance=MemoryProvenance.EPISODIC_EVENT,
                        content=content,
                        salience=float(getattr(ev, "salience", 0.3)),
                        priority=8,
                        tokens_estimate=self.estimate_tokens(content),
                    ))

        return items

    def rank(self, items: list[ContextItem]) -> list[ContextItem]:
        """Step 2: RANK items deterministically by priority asc, then salience desc."""
        return sorted(items, key=lambda it: (it.priority, -it.salience))

    def budget(
        self,
        ranked_items: list[ContextItem],
        budget_tokens: int,
    ) -> tuple[list[ContextItem], list[ContextItem]]:
        """Step 3: BUDGET enforcement. Adhere to token limits, dropping lowest ranked items."""
        included: list[ContextItem] = []
        dropped: list[ContextItem] = []
        used_tokens = 0

        for item in ranked_items:
            # Priority 0 is always included (essential identity)
            if item.priority == 0:
                included.append(item)
                used_tokens += item.tokens_estimate
                continue

            if used_tokens + item.tokens_estimate <= budget_tokens:
                included.append(item)
                used_tokens += item.tokens_estimate
            else:
                dropped.append(item)

        return included, dropped

    def format_for_cognition(
        self,
        goal: str,
        included: list[ContextItem],
        dropped: list[ContextItem],
        budget_tokens: int,
    ) -> CompiledContext:
        """Step 4 & 5: Tag PROVENANCE and FORMAT FOR COGNITION PROFILE."""
        system_sections: list[str] = []
        provenance_breakdown: dict[str, int] = {}

        # Group included items by provenance
        by_provenance: dict[MemoryProvenance, list[ContextItem]] = {}
        for item in included:
            by_provenance.setdefault(item.provenance, []).append(item)
            provenance_breakdown[item.provenance.value] = (
                provenance_breakdown.get(item.provenance.value, 0) + 1
            )

        # Build system prompt in structured provenance blocks
        for prov in (
            MemoryProvenance.IDENTITY,
            MemoryProvenance.RUNTIME_TRUTH,
            MemoryProvenance.SELF_STATE,
            MemoryProvenance.LEARNED_SKILL,
            MemoryProvenance.REFLEXION,
            MemoryProvenance.SEMANTIC_CLAIM,
            MemoryProvenance.RETRIEVED_DOCUMENT,
            MemoryProvenance.DEVICE_OBSERVATION,
            MemoryProvenance.EPISODIC_EVENT,
        ):
            group = by_provenance.get(prov)
            if not group:
                continue
            header = f"=== [{prov.value}] ==="
            body = "\n".join(it.content for it in group)
            system_sections.append(f"{header}\n{body}")

        system_prompt = "\n\n".join(system_sections)
        user_prompt = goal.strip()

        total_text = f"{system_prompt}\n\n{user_prompt}"
        total_chars = len(total_text)
        estimated_tokens = self.estimate_tokens(total_text)

        return CompiledContext(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            items_included=included,
            items_dropped=dropped,
            total_chars=total_chars,
            estimated_tokens=estimated_tokens,
            budget_tokens=budget_tokens,
            provenance_breakdown=provenance_breakdown,
            is_budget_exceeded=len(dropped) > 0,
        )

    def compile(
        self,
        goal: str,
        *,
        identity: Any = None,
        self_state: Any = None,
        runtime_truth: str | None = None,
        claims: list[dict[str, Any]] | None = None,
        events: list[Any] | None = None,
        reflections: list[Any] | None = None,
        documents: list[dict[str, Any]] | None = None,
        skills: list[dict[str, Any]] | None = None,
        observations: list[dict[str, Any]] | None = None,
        budget_tokens: int | None = None,
    ) -> CompiledContext:
        """Run the full 5-stage context compilation pipeline."""
        limit = budget_tokens or self.default_budget_tokens
        selected = self.select(
            goal,
            identity=identity,
            self_state=self_state,
            runtime_truth=runtime_truth,
            claims=claims,
            events=events,
            reflections=reflections,
            documents=documents,
            skills=skills,
            observations=observations,
        )
        ranked = self.rank(selected)
        included, dropped = self.budget(ranked, limit)
        return self.format_for_cognition(goal, included, dropped, limit)
