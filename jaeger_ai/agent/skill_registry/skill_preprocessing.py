"""SKILL.md template-variable preprocessing (audit A6).

A playbook skill is a `SKILL.md` the agent reads on demand. Until now its
body was surfaced raw — a playbook could not parameterise itself or
inject a computed value (the instance name, today's date, its own folder
path). This module expands `{{var}}` placeholders in the body before the
model sees it.

Scope: **template variables only**. Hermes's `skill_preprocessing.py`
also runs *inline shell* in a SKILL.md — that is deliberately NOT ported
here: executing shell while merely *viewing* a skill would be an
un-gated `run_shell`, bypassing the tier system and the `skills_guard`
scan. Inline execution, if ever added, must route through the tier
system. Unknown placeholders are left untouched — a skill that contains
a literal `{{` for its own reasons is never mangled.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

# {{ name }} — a word placeholder, optional surrounding whitespace.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _build_vars(skill_name: str, skill_folder: Path | None) -> dict[str, str]:
    """The substitution table — instance/skill identity plus the clock."""
    now = datetime.datetime.now()
    vars_: dict[str, str] = {
        "date": now.strftime("%Y-%m-%d"),
        "today": now.strftime("%Y-%m-%d"),
        "datetime": now.strftime("%Y-%m-%d %H:%M"),
        "time": now.strftime("%H:%M"),
        "os": sys.platform,
        "platform": sys.platform,
        "skill_name": skill_name or "",
        "skill_folder": str(skill_folder) if skill_folder else "",
    }
    # Instance paths — only when an instance is bound (skipped in tests
    # / standalone use).
    try:
        from jaeger_ai.core.context import _require_layout

        layout = _require_layout()
        vars_["instance_name"] = layout.root.name
        vars_["instance_dir"] = str(layout.root)
        vars_["skills_dir"] = str(layout.skills_dir)
    except Exception:  # noqa: BLE001 — no instance bound is fine
        pass
    return vars_


def preprocess_skill(
    body: str,
    *,
    skill_name: str = "",
    skill_folder: Path | None = None,
) -> str:
    """Expand `{{var}}` placeholders in a SKILL.md body.

    Returns ``body`` unchanged when it carries no placeholders. An
    unknown `{{var}}` is left exactly as written."""
    if not body or "{{" not in body:
        return body
    vars_ = _build_vars(skill_name, skill_folder)

    def _sub(m: re.Match) -> str:
        return vars_.get(m.group(1).lower(), m.group(0))

    return _PLACEHOLDER_RE.sub(_sub, body)


__all__ = ["preprocess_skill"]
