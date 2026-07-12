---
name: subagent-driven-development
description: "Load this to execute a written implementation plan task-by-task with a two-stage review gate (spec compliance, then code quality) between every task, tracked on a todo list."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [read_file, todo, terminal, write_file, use_skill, delegate_task]
metadata:
  jros:
    tags: [execution, workflow, review-gates, tdd, implementation]
    category: software-development
    related_skills: [writing-plans, requesting-code-review, test-driven-development]
---

# TASK-BY-TASK DEVELOPMENT WITH REVIEW GATES

Execute a plan one task at a time. After each task, run TWO review passes with fresh
eyes — spec compliance FIRST, then code quality — before moving on.

CORE: each task gets clean, focused context (no parent history) and two gates.
Fresh-eyes review catches under/over-building and bugs before they compound.

FRESH CONTEXT = `delegate_task`. `delegate_task(["…"])` hands a focused subtask to a
fresh sub-agent that runs with NO parent history but shares this instance's memory and
tools — exactly the clean-context isolation this skill needs. Pass one item for a
single sub-agent, 2+ to fan out (up to 2 concurrent; their LLM turns serialize). Use it
to run each implementation task and each review pass in isolation. (For sustained
background work, prefer Deep Think over delegation.)

## WHEN TO USE
- You have an implementation plan (from writing-plans) or clear per-task requirements.
- Tasks are mostly independent and quality/spec compliance matter.

## TOOLS
- read_file("docs/plans/feature.md") — read the plan ONCE, up front.
- todo([...]) — seed every task; flip status as you go (state offloading).
- delegate_task(["implement task N per this spec: …"]) — run a task or a review in a
  fresh sub-agent (clean context). One item = one sub-agent; 2+ fan out (max 2 concurrent).
- terminal("pytest ... && git commit ...") — run tests + commit each task.
- write_file("review_notes.md", ...) — record review findings between passes.
- use_skill("requesting-code-review") — the quality-gate recipe (scan + review pass).

## SOP

### Phase 1 — Parse the plan (once)
`read_file` the plan. Extract EVERY task's full text now — do not re-open the plan mid-
task; carry each task's text forward yourself. Seed the todo list:
```python
todo([
  {"id": "task-1", "content": "Create User model with email field", "status": "pending"},
  {"id": "task-2", "content": "Add password hashing utility",        "status": "pending"},
])
```

### Phase 2 — Per task, in order
For EACH task:

1. IMPLEMENT in a fresh sub-agent: `delegate_task(["Implement <task N>: <full spec>.
   Follow TDD — failing test first, minimal impl, full suite green, commit."])`. The
   sub-agent starts with no parent history (clean context). It follows TDD:
   write failing test -> run, expect FAIL -> minimal impl -> run, expect PASS -> run the
   full suite for regressions -> commit.

2. SPEC-COMPLIANCE PASS (gate 1) — run it as its OWN `delegate_task(["Review the diff
   for <task N> against ONLY this spec: …"])` so the reviewer is genuinely independent
   of the implementer. Judge the result against ONLY the task spec:
   - Every requirement implemented? Paths + signatures match? Behavior matches?
   - Nothing extra added (no scope creep)?
   Output PASS or a list of gaps. Gaps -> fix, re-run this pass. Proceed only on PASS.

3. CODE-QUALITY PASS (gate 2), only after spec PASS. Judge the same files for:
   conventions/style, error handling, clear names, test coverage, edge cases, security.
   Output: Critical / Important / Minor + verdict APPROVED or REQUEST_CHANGES.
   Use `use_skill("requesting-code-review")` to run the full scan-and-review pipeline
   here. Not APPROVED -> fix, re-review. Proceed only when approved.

4. MARK DONE: `todo([{"id":"task-1","content":"...","status":"completed"}], merge=True)`

### Phase 3 — Final integration review
After ALL tasks: fresh pass over the whole change — do components fit together, any
cross-task inconsistencies, all tests green, ready to merge?
`terminal("pytest tests/ -q && git diff --stat")`, then a final commit if needed.

## RED FLAGS — never do these
- Start without a plan. Skip either gate. Proceed with open Critical/Important issues.
- Run two implement passes on tasks that touch the SAME files (serialize them).
- Re-open the plan file per task instead of carrying the extracted text.
- Skip scene-setting context, or run the quality gate before spec PASS (wrong order).
- Let self-review replace the gate passes — both spec and quality gates are required.

## HANDLING ISSUES
- Task fails: start a fresh fix pass with specific instructions on what went wrong;
  don't patch it inline while carrying polluted context.
- Reviewer finds issues: fix, then re-run the SAME gate. Don't skip the re-review.

## STATE OFFLOADING
The todo list is the source of truth for progress. For long runs, append gate verdicts
to review_notes.md (write_file/append) so nothing is lost between passes.

## ERROR HATCH
If a task's review keeps failing after 2 fix cycles, stop and escalate to the user with
the specific blocking issues — do not keep looping or lower the bar to "close enough".

## DONE WHEN
Every todo task is completed, both gates passed for each, the full suite is green, and
the final integration pass is clean.

## FURTHER READING (lazy-load when relevant)
- `read_file("references/context-budget-discipline.md")` — PEAK/GOOD/DEGRADING/POOR
  context tiers + read-depth rules. Load for multi-phase plans or large artifacts.
- `read_file("references/gates-taxonomy.md")` — the four gate types (Pre-flight,
  Revision, Escalation, Abort) with entry/failure/resume rules. Load when designing gates.
