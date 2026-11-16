"""``skill_manage`` — the agent writes and maintains its own playbook skills.

Hermes-style procedural memory: after a complex task (or when the owner asks)
the agent saves the working procedure as ``skills/<name>/SKILL.md`` and keeps it
current. Every change is versioned (``memory/skill_history``) and logged in
``skill_revisions.jsonl``; ``rollback`` restores any earlier version. Builtin
skills are read-only.
"""

from __future__ import annotations

import re

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import _require_layout
from jaeger_agent.skill_improvement import skill_history as sh


_ONE_OFF_NAME = re.compile(r"(?:^|[-_])(?:demo|test|tests|probe|tmp|temp|scratch|audit|parity|check|trial)(?:[-_]|$)", re.I)
_MISSING_TOOL_NOTES = re.compile(
    r"tool[- ]not[- ]found|not (?:on|in) this (?:session'?s? )?tool surface|absent on this tool surface|"
    r"reported missing|is not available in this session|isn'?t callable|not callable here|outside this request scope",
    re.I)


def _creation_refusal(name: str, content: str, summary: str) -> str | None:
    """Skills are for reusable procedures, not one-off runs (2026-11-16 audit: a
    parity demo saved 'schedule-surface-cancel', a workaround for a missing tool)."""
    if _ONE_OFF_NAME.search(name or ""):
        return (f"Not creating {name!r}: names with demo/test/audit/tmp mark a one-off run. "
                "Only save a skill for a procedure the owner will want again.")
    if _MISSING_TOOL_NOTES.search(content or ""):
        return ("Not creating this skill: it documents a tool being missing or out of scope in this session. "
                "That is a bug to report in your answer, not a reusable procedure.")
    if len((summary or "").strip()) < 15:
        return ("To create a skill, give a summary (15+ characters) saying why this procedure is reusable "
                "beyond the current request. Skip saving when it is a one-off.")
    return None


@register_tool_from_function(name="skill_manage", side_effect="write")
def skill_manage(action: str, name: str, content: str = "", summary: str = "",
                 old: str = "", new: str = "", version: str = "") -> dict[str, Any]:
    """Create, edit, patch, inspect or roll back YOUR OWN playbook skills.

    Use after finishing a non-trivial, reusable task (several tool calls, a
    tricky fix, a workflow the owner will want again) to save the procedure,
    or to correct a skill you used that turned out wrong or outdated.

    action:
      • "create"  — new skill. content = full SKILL.md starting with YAML
                    frontmatter (name: <name>, description: <when to use it>),
                    then concise steps, pitfalls and verification.
      • "edit"    — replace the whole SKILL.md of an existing instance skill.
      • "patch"   — replace the exact text ``old`` with ``new`` (must match once).
      • "view"    — current SKILL.md text.
      • "history" — list saved versions (v0 = original before first managed edit).
      • "rollback"— restore ``version`` (e.g. "v2"); the rollback is itself a version.
    summary: one line on what changed and why (recorded in the revision log).
             For "create" it must say why the procedure is reusable; one-off
             runs (demo/test/audit names) and notes about a missing tool are refused.
    Builtin skills are read-only; create a new skill instead.
    """
    layout = _require_layout()
    act = (action or "").strip().lower()
    try:
        n = sh._clean_name(name)
        if act == "create":
            refusal = _creation_refusal(n, content, summary)
            if refusal:
                return {"ok": False, "error": refusal, "created": False}
            return sh.write(layout, n, content, summary=summary or "created", must_exist=False)
        if act == "edit":
            return sh.write(layout, n, content, summary=summary or "edited", must_exist=True)
        if act == "patch":
            folder = sh.skill_folder(layout, n)
            if folder is None:
                return {"ok": False, "error": f"No instance skill named {n!r}"}
            text = (folder / "SKILL.md").read_text(encoding="utf-8")
            if not old or text.count(old) != 1:
                return {"ok": False, "error": "'old' must match exactly once in SKILL.md",
                        "matches": text.count(old) if old else 0}
            return sh.write(layout, n, text.replace(old, new, 1),
                            summary=summary or "patched", must_exist=True)
        if act == "view":
            folder = sh.skill_folder(layout, n)
            if folder is None:
                return {"ok": False, "error": f"No instance skill named {n!r}"}
            return {"ok": True, "skill": n, "content": (folder / "SKILL.md").read_text(encoding="utf-8")}
        if act == "history":
            return {"ok": True, "skill": n, "versions": sh.versions(layout, n)}
        if act == "rollback":
            return sh.rollback(layout, n, version, origin="self-improvement")
        return {"ok": False, "error": "action must be create, edit, patch, view, history or rollback"}
    except sh.SkillHistoryError as exc:
        return {"ok": False, "error": str(exc)}


__all__ = ["skill_manage"]
