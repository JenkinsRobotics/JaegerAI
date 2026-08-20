"""Hermes-compatible argument shapes for ``delegate_task``.

Jaeger's tool historically took ``subtasks: list[str]``. Hermes accepts
either a single ``goal`` or a batch ``tasks`` list (strings or
``{goal, context}`` dicts), plus ``role=leaf|orchestrator``.

The runtime already fans a list out in parallel, bounded by the live
brain's profile, and can detach with ``background=True``. This module
is the adapter so either calling convention produces that list.
"""

from __future__ import annotations

from typing import Any

LEAF = "leaf"
ORCHESTRATOR = "orchestrator"
ROLES = (LEAF, ORCHESTRATOR)


def _one(goal: str, context: str = "") -> str:
    text = (goal or "").strip()
    extra = (context or "").strip()
    if not text:
        return ""
    if extra:
        return f"{text}\n\nContext:\n{extra}"
    return text


def _from_item(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        goal = str(
            item.get("goal") or item.get("task") or item.get("prompt") or ""
        )
        context = str(item.get("context") or "")
        return _one(goal, context)
    return str(item).strip()


def collect_goals(
    *,
    subtasks: Any = None,
    goal: Any = None,
    tasks: Any = None,
    context: Any = None,
) -> list[str]:
    """Normalize Hermes + Jaeger argument shapes into a goal list.

    Order: the single ``goal`` first (Hermes single-task form), then
    ``tasks``, then ``subtasks``. Duplicates after strip are kept —
    two identical research questions are still two workers.
    """
    out: list[str] = []
    single = _one(str(goal or ""), str(context or ""))
    if single:
        out.append(single)
    for bucket in (tasks, subtasks):
        if bucket is None:
            continue
        if isinstance(bucket, (str, dict)):
            bucket = [bucket]
        try:
            items = list(bucket)
        except TypeError:
            continue
        for item in items:
            text = _from_item(item)
            if text:
                out.append(text)
    return out


def normalize_role(role: Any) -> str:
    name = str(role or LEAF).strip().lower()
    return name if name in ROLES else LEAF


def leaf_child_depth(max_depth: int) -> int:
    """Thread-local depth a leaf child starts at so nested
    ``delegate_task`` refuses immediately.

    Orchestrator children start at parent+1 (the normal increment).
    A leaf is a worker: it must not spawn. Seeding the child's depth
    counter at the cap makes the existing recursion guard do that
    without stripping the tool from the child's catalogue.
    """
    return max(0, int(max_depth))


__all__ = [
    "LEAF",
    "ORCHESTRATOR",
    "ROLES",
    "collect_goals",
    "leaf_child_depth",
    "normalize_role",
]
