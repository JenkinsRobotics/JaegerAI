"""Agentic trajectory evaluation (SpanTree from pydantic-ai) & compaction verifier (AG2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(slots=True)
class TraceSpan:
    name: str
    kind: str  # "model" | "tool" | "approval" | "cognition"
    duration_ms: float = 0.0
    ok: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list[TraceSpan] = field(default_factory=list)


class SpanTree:
    """Queryable execution span tree for deterministic agent trajectory grading."""

    def __init__(self, roots: Sequence[TraceSpan]) -> None:
        self.roots = list(roots)

    def walk(self) -> list[TraceSpan]:
        out: list[TraceSpan] = []

        def _visit(span: TraceSpan) -> None:
            out.append(span)
            for child in span.children:
                _visit(child)

        for r in self.roots:
            _visit(r)
        return out

    def tool_names(self) -> list[str]:
        return [s.name for s in self.walk() if s.kind == "tool"]

    def has_tool_call(self, tool_name: str, *, ok_only: bool = True) -> bool:
        return any(
            s.kind == "tool" and s.name == tool_name and (s.ok or not ok_only)
            for s in self.walk()
        )

    def tool_sequence_contains(self, expected_order: Sequence[str]) -> bool:
        names = self.tool_names()
        idx = 0
        for name in names:
            if idx < len(expected_order) and name == expected_order[idx]:
                idx += 1
        return idx == len(expected_order)

    def error_count(self) -> int:
        return sum(1 for s in self.walk() if not s.ok)


@dataclass(slots=True)
class CompactionVerification:
    passed: bool
    missing_anchors: list[str]
    compression_ratio: float


def verify_compaction_integrity(
    original_messages: Sequence[Mapping[str, Any]],
    compacted_messages: Sequence[Mapping[str, Any]],
    *,
    required_anchors: Sequence[str],
) -> CompactionVerification:
    """Verify compacted conversation retains critical owner goals, constraints, and facts (AG2 pattern)."""
    orig_len = sum(len(str(m.get("content") or "")) for m in original_messages)
    comp_text = "\n".join(str(m.get("content") or "") for m in compacted_messages)
    comp_low = comp_text.lower()
    missing = [a for a in required_anchors if a.lower() not in comp_low]
    ratio = round(len(comp_text) / max(1, orig_len), 3)
    return CompactionVerification(passed=len(missing) == 0, missing_anchors=missing, compression_ratio=ratio)


__all__ = ["CompactionVerification", "SpanTree", "TraceSpan", "verify_compaction_integrity"]
