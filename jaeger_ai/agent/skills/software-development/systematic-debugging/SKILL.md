---
name: systematic-debugging
description: "Find the root cause of a bug BEFORE touching a fix — a 4-phase investigate → analyze → hypothesize → fix flow. Load this for test failures, crashes, unexpected behavior, perf/build/integration issues, or any 'just one quick fix' urge."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [read_file, search_files, terminal, web_search, append_file, todo]
metadata:
  jros:
    tags: [debugging, troubleshooting, root-cause, investigation, testing]
    category: software-development
    related_skills: [test-driven-development, node-inspect-debugger]
---

# SYSTEMATIC DEBUGGING

Random fixes waste time and spawn new bugs. Symptom patches mask the real defect.

THE IRON LAW: NO FIX WITHOUT ROOT-CAUSE INVESTIGATION FIRST.
If Phase 1 is not complete, you may not propose a fix.

## WHEN TO USE
Any technical failure: failing test, production bug, wrong behavior, perf problem,
build break, integration issue. ESPECIALLY when under time pressure, when a "quick
fix" looks obvious, or when a previous fix did not work. Simple bugs have root causes too.

## TOOLS
- `read_file(path=…)` — read the failing source with line numbers.
- `search_files(query=…, path=…)` — grep for the error string, callers, where a value is set.
- `terminal(command=…)` — reproduce the bug, run the test, inspect git history.
- `web_search(query=…)` — research an unfamiliar error message or library behavior.
- `append_file(path="skills/debug-log.md", text=…)` — offload evidence (see STATE OFFLOADING).
- `todo(...)` — track the phase you are in when the investigation spans many steps.

## STATE OFFLOADING (mandatory once you have >3 pieces of evidence)
Do not hold the investigation in your head. After each finding, append it:
`append_file(path="skills/debug-log.md", text="EVIDENCE: <what you saw> @ <file:line>")`
Record: the error, repro steps, recent changes, each hypothesis + its outcome.

## PHASE 1 — ROOT CAUSE (complete before any fix)
1. READ THE ERROR. Full stack trace, line numbers, file paths, error codes. The exact
   solution is often already in the message. `read_file` the referenced source.
2. REPRODUCE CONSISTENTLY. `terminal("pytest tests/test_x.py::test_name -v --tb=long")`.
   Not reproducible? Gather more data — do NOT guess.
3. CHECK RECENT CHANGES. `terminal("git log --oneline -10")`, `terminal("git diff")`.
   New deps, config, or commits are prime suspects.
4. INSTRUMENT COMPONENT BOUNDARIES (multi-component systems: API→service→DB, CI→build→deploy).
   Log data in and out of each boundary, run once, find WHERE it breaks, then dig into
   that one component.
5. TRACE DATA FLOW when the error is deep in the stack. Find where the bad value ORIGINATES.
   `search_files(query="bad_var =", path="src/")` and `search_files(query="func_name(", path="src/")`.
   Trace upstream to the source; fix there, not at the symptom.

PHASE 1 DONE WHEN: error understood, bug reproduced, recent changes reviewed, evidence
logged, problem isolated to specific code, and you have a root-cause hypothesis.
STOP — do not proceed until you know WHY it happens.

## PHASE 2 — PATTERN ANALYSIS
1. Find working examples of the same pattern in-repo: `search_files(query="similar_pattern", path="src/")`.
2. Read any reference implementation COMPLETELY — every line, no skimming.
3. List EVERY difference between working and broken, however small. Never assume "that can't matter".
4. Understand dependencies: what config, env, and assumptions the code needs.

## PHASE 3 — HYPOTHESIS AND TEST
1. State ONE hypothesis: "X is the root cause because Y." Write it to the debug log.
2. Test with the SMALLEST possible change — one variable at a time.
3. Worked? → Phase 4. Didn't? → form a NEW hypothesis. Do NOT stack fixes.
4. Don't understand something? Say so, research (`web_search`), or ask the user. Never pretend.

## PHASE 4 — IMPLEMENTATION
1. Write a failing regression test first (use the test-driven-development skill).
2. Implement ONE fix at the root cause. No "while I'm here" changes, no bundled refactors.
3. Verify: `terminal("pytest tests/test_x.py::test_regression -v")` then `terminal("pytest tests/ -q")`
   for no regressions.
4. RULE OF THREE — if the fix fails: count attempts. <3 → return to Phase 1 with new info.
   ≥3 → STOP and question the architecture (step 5). Never attempt fix #4 blindly.
5. 3+ FAILURES = WRONG ARCHITECTURE, not a bad hypothesis. Symptoms: each fix exposes new
   coupling elsewhere, fixes need "massive refactoring", each fix breaks something new.
   STOP and discuss fundamentals with the user before any more fixes.

## RED FLAGS — STOP, RETURN TO PHASE 1
"Quick fix now, investigate later" · "just try changing X" · "add several changes, run tests" ·
"skip the test, I'll verify by hand" · "it's probably X" · proposing fixes before tracing data
flow · "one more fix attempt" after 2+ failures · each fix reveals a new problem elsewhere.

## ERROR HATCH
If you cannot reproduce the bug after two attempts: stop guessing, add boundary
instrumentation (Phase 1.4), and collect a fresh run's evidence into the debug log before
proposing anything. If reproduction is still impossible, report that to the user with the
data you have rather than shipping a speculative fix.

## DONE WHEN
Root cause is named and evidenced, a regression test failed then passes, the single
targeted fix is in, and the full suite is green with pristine output.
