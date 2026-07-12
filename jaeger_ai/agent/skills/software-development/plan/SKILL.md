---
name: plan
description: "Load this for plan-only turns: research the repo read-only and save a concrete markdown plan, without editing project code or running mutating commands."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [read_file, search_files, execute_code]
metadata:
  jros:
    tags: [planning, plan-mode, read-only, workflow]
    category: software-development
    related_skills: [writing-plans, subagent-driven-development]
---

# PLAN MODE

The user wants a PLAN, not execution. This turn is planning only.

## RULES
- Do NOT implement code or edit project files (the plan file is the ONE exception).
- Do NOT run mutating commands: no commit, push, install, or external side effects.
- Inspecting the repo is fine: read_file and search_files are read-only.
- Deliverable = one markdown plan file saved in the workspace.

## TOOLS
- read_file("path") — read any file to gather context.
- search_files("pattern", path="src/") — grep contents; add target="files" to list files.
- execute_code(...) — the ONLY write here: save the plan into the workspace
  (write_file is sandboxed to skills/, so it cannot reach the project tree).

## PLAN CONTENTS
Concrete and actionable. Include when relevant:
- Goal
- Current context / assumptions
- Proposed approach
- Step-by-step plan
- Files likely to change (exact paths)
- Tests / validation (likely test targets + verify commands)
- Risks, tradeoffs, open questions

## SAVE
```python
execute_code('''
from pathlib import Path, PurePath
import datetime
d = Path(".jros/plans"); d.mkdir(parents=True, exist_ok=True)
ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
(d / f"{ts}-SLUG.md").write_text(PLAN_TEXT)
print("saved", ts)
''')
```
If the runtime handed you a specific target path, use that exact path instead.

## INTERACTION
- Request clear enough -> write the plan directly.
- No explicit task with `/plan` -> infer it from the current conversation.
- Genuinely underspecified -> ask ONE brief clarifying question, then plan.

## DONE WHEN
The plan markdown is saved and you have replied with a one-line summary plus the saved
path. No project code was changed.
