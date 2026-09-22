"""Models and Data Classes for Context Compilation (Workstream 6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from .provenance import MemoryProvenance


@dataclass
class ContextItem:
    """A candidate piece of information considered during context compilation."""

    item_id: str
    provenance: MemoryProvenance
    content: str
    salience: float = 0.5
    tokens_estimate: int = 0
    priority: int = 10  # Lower number = higher priority (0 = essential)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledContext:
    """The measurable, structured outcome of a ContextCompiler compilation run."""

    system_prompt: str
    user_prompt: str
    items_included: list[ContextItem]
    items_dropped: list[ContextItem]
    total_chars: int
    estimated_tokens: int
    budget_tokens: int
    provenance_breakdown: dict[str, int]
    is_budget_exceeded: bool = False
