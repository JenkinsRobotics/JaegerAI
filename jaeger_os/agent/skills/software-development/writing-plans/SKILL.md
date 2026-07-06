---
name: writing-plans
description: "Load this to turn a spec or feature request into a step-by-step implementation plan file (exact paths, copy-pasteable code, verify commands) before any code gets written."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [read_file, search_files, write_file, execute_code, terminal, todo]
metadata:
  jros:
    tags: [planning, design, implementation, tdd, workflow]
    category: software-development
    related_skills: [plan, subagent-driven-development, requesting-code-review]
---

# WRITING IMPLEMENTATION PLANS

Write a plan an implementer with ZERO context can follow. If they'd have to guess,
the plan is incomplete. Every task ships exact paths + complete code + a verify command.

CORE: bite-sized tasks (2-5 min each), DRY, YAGNI, TDD, commit after each task.

## WHEN TO USE
- Before any multi-step feature or complex requirement.
- Before handing work to subagent-driven-development.
- Even for "simple" features (assumptions cause bugs) and solo work (future-you needs it).

## TOOLS
- read_file("src/app.py") — read anything to understand the codebase.
- search_files("pattern", path="src/") — grep file contents for similar features.
- search_files("", path="src/", target="files") — list files in a dir.
- execute_code(...) — write the finished plan to a project path (write_file is skills/-only).
- terminal("git add ... && git commit ...") — save/commit the plan file.
- todo([...]) — track the tasks you are drafting if the plan is large.

## SOP

### Phase 1 — Understand (read only)
1. Read the requirements / user description / acceptance criteria.
2. Explore: read_file on key files, search_files for similar patterns and existing tests.
3. Decide architecture, file layout, dependencies, and test strategy.

### Phase 2 — Draft tasks
Order: setup -> core (TDD each) -> edge cases -> integration -> cleanup.
Each task = ONE small unit. "Build auth system" is too big. "Create User model with
email field" is right. If a task touches 5 files or 50 lines, split it.

### Phase 3 — Write the plan document
Start with this header:
```markdown
# [Feature] Implementation Plan
> Execute with the subagent-driven-development skill, task by task.
**Goal:** [one sentence]
**Architecture:** [2-3 sentences]
**Tech Stack:** [key libs]
---
```
Then one block PER task, in this exact shape:
```markdown
### Task N: [Descriptive name]
**Objective:** [one sentence]
**Files:**
- Create: `exact/path/new_file.py`
- Modify: `exact/path/existing.py:45-67`
- Test:   `tests/path/test_file.py`

Step 1 — Write failing test  (paste the COMPLETE test code)
Step 2 — Run it, expect FAIL: `pytest tests/path/test_file.py::test_x -v`
Step 3 — Write minimal impl  (paste the COMPLETE code)
Step 4 — Run it, expect PASS: `pytest tests/path/test_file.py::test_x -v`
Step 5 — Commit: `git add <files> && git commit -m "feat: ..."`
```
Rules for every task: exact paths (never "the config file"), complete copy-pasteable
code (never "add validation"), exact commands WITH expected output, a verify step.

### Phase 4 — Self-check the plan
- [ ] Tasks sequential + logical, each 2-5 min.
- [ ] Paths exact, code complete, commands have expected output.
- [ ] DRY / YAGNI (no speculative fields) / TDD cycle in every code task.

### Phase 5 — Save it
Write the plan into the project (write_file only reaches skills/, so use execute_code):
```python
execute_code('''
from pathlib import Path
p = Path("docs/plans"); p.mkdir(parents=True, exist_ok=True)
(p / "2026-07-01-feature-name.md").write_text(PLAN_TEXT)
print("saved")
''')
```
Then commit: `terminal("git add docs/plans/ && git commit -m 'docs: add plan for X'")`

## STATE OFFLOADING
For a plan with >3 tasks, seed a todo list (todo([...])) so execution can track each
task's status later.

## ERROR HATCH
If you can't find a file or pattern, do NOT invent a path — search_files twice with
different terms, and if still unknown, write the task with a TODO note asking the
implementer to locate it. Never ship a guessed path as fact.

## DONE WHEN
A saved markdown plan exists where each task has exact paths, complete code, a run
command with expected output, and a commit line — and a reader with no context could
execute it top to bottom. Hand off: "Plan saved at <path>. Execute with
subagent-driven-development?"
