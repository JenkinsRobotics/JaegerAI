"""The `reflect` tool — the closing step of the research → plan → execute →
verify → REFLECT loop.

Deliberately simple for now: after a non-trivial multi-step task, the agent
records a brief after-action note to a human-readable ``reflections.md`` in the
instance. The point today is to BUILD THE PRACTICE of closing the loop.

Future (backlog, dev/docs/future_backlog.md): the reflection feeds skill
creation + pruning — a novel repeatable task becomes a new skill, a fumbled one
triggers a skill review. For now it just journals; nothing auto-creates skills.

Distinct from ``skill_note`` (which is per-SKILL-use telemetry that feeds the
Deep Think skill-review sweep). ``reflect`` is per-TASK, skill or not.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
from jaeger_os.core.context import get_layout


def _reflections_md(layout: Any) -> Path:
    return Path(layout.memory_dir) / "reflections.md"


@register_tool_from_function(name="reflect", side_effect="write")
def reflect(summary: str, worked: str = "", hard: str = "",
            lesson: str = "") -> dict[str, Any]:
    """Close the loop on a task you just finished. After a non-trivial,
    multi-step job, call this ONCE at the end to record a brief
    after-action note — it's appended to ``reflections.md`` so a future
    you can learn from it.

      * ``summary`` — one line: what the task was + how it turned out.
      * ``worked``  — the approach/tool/order that succeeded.
      * ``hard``    — what was slow, failed, or needed a retry, and why.
      * ``lesson``  — the ONE reusable takeaway (a pattern worth a skill,
        a user preference, a pitfall to avoid next time).

    Skip it for trivial one-tool turns. This is the REFLECT step of
    research → plan → execute → verify → reflect. (For per-skill-use
    telemetry that feeds skill review, use ``skill_note`` instead.)"""
    clean = (summary or "").strip()
    if not clean:
        return {"ok": False, "error": "reflect needs a summary"}
    layout = get_layout()
    path = _reflections_md(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    block = [f"## {stamp} — {clean}"]
    if worked.strip():
        block.append(f"- Worked: {worked.strip()}")
    if hard.strip():
        block.append(f"- Hard: {hard.strip()}")
    if lesson.strip():
        block.append(f"- Lesson: {lesson.strip()}")
    entry = "\n".join(block) + "\n\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return {"ok": True, "path": str(path), "saved": True,
            "note": "reflection recorded — closing the loop"}


__all__ = ["reflect"]
