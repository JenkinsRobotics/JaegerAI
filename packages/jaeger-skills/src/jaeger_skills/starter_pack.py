"""Pre-bundled verified starter SKILL.md pack for fresh JaegerAI installations.

Gives every new user instant Day-1 competence out of the box (no blank-slate
tinkering) while remaining 100% user-owned: skills are copied into
`<state_dir>/skills/<name>/SKILL.md` only if missing (never overwriting user edits).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .store import validate_skill_markdown

__all__ = ["STARTER_SKILLS", "ensure_starter_skills"]

STARTER_SKILLS: dict[str, str] = {
    "morning-briefing": """---
name: morning-briefing
description: Deliver a concise daily status brief covering goals, scheduled jobs, memory notes, and recent autonomous actions.
---

# Morning Briefing

1. Inspect persistent goals (`persistent_goals`), scheduled jobs (`list_scheduled_jobs`), and recent memory facts (`memory_list`).
2. Summarize what changed since the owner's last session in 3–5 crisp bullets.
3. Highlight anything awaiting owner approval and ask what to focus on first.
""",
    "code-debug-verify": """---
name: code-debug-verify
description: Reproduce a bug, inspect relevant files, apply a minimal lint-guarded fix, and run verification tests.
---

# Code Debug & Verify

1. Read the failing code and tests first (`read_file`, `search_files`).
2. Reproduce the failure cleanly via `shell` or `execute_code`.
3. Apply the smallest targeted edit (`edit_file` / `apply_patch`), then re-run the test suite to confirm zero regressions.
4. Report exact file paths and test counts without fluff.
""",
    "web-research-brief": """---
name: web-research-brief
description: Research a topic using web_search and web_fetch, verify claims against primary sources, and return concise takeaways.
---

# Web Research Brief

1. Run targeted queries with `web_search` and inspect primary documentation URLs with `web_fetch`.
2. Separate directly verified facts from assumptions or missing data.
3. Return a crisp summary with source links and clear next options.
""",
    "inbox-triage": """---
name: inbox-triage
description: Inspect macOS Apple Mail mailboxes, categorize clutter vs important threads, and move messages safely with owner confirmation.
---

# Inbox Triage

1. Discover configured accounts and mailboxes via `list_mailboxes`.
2. Summarize urgent vs low-priority messages without deleting anything silently.
3. Confirm target mailbox before calling `batch_move_mail`.
""",
    "goal-progress-check": """---
name: goal-progress-check
description: Review active multi-day persistent goals, verify current state, and update durable checkpoints cleanly.
---

# Goal Progress Check

1. Call `persistent_goals` with `mode="list"` to review active goals by priority.
2. Check workspace or memory state for any recent progress (`session_search`, `memory_list`).
3. Update the goal checkpoint and propose the single clearest next milestone.
""",
    "system-health-check": """---
name: system-health-check
description: Audit Jaeger's live Gateway health, 32 GB memory budget, active model routing, Droid peripherals, and embodiments.
---

# System Health Check

1. Check connected peripherals (`droid_devices`), Minecraft state (`minecraft_status`), and allowlisted remote hosts (`remote_hosts`).
2. Verify any pending scheduled jobs (`list_scheduled_jobs`) or workspace skills (`search_workspace_skills`).
3. Report concrete health status and flag any real blockers clearly.
""",
}


def ensure_starter_skills(skills_dir: Path) -> dict[str, Any]:
    """Seed missing verified starter skills into `<state_dir>/skills/` without overwriting existing ones."""
    root = Path(skills_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    skipped: list[str] = []
    for name, markdown in STARTER_SKILLS.items():
        clean_md = validate_skill_markdown(name, markdown)
        target_dir = root / name
        target_file = target_dir / "SKILL.md"
        if target_file.exists():
            skipped.append(name)
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(clean_md, encoding="utf-8")
        installed.append(name)
    return {"installed": installed, "skipped": skipped, "skills_dir": str(root)}
