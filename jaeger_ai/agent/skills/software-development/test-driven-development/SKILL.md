---
name: test-driven-development
description: "Enforce strict RED-GREEN-REFACTOR: write a failing test, watch it fail, then write minimal code to pass. Load this before implementing ANY feature, bug fix, refactor, or behavior change."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [terminal, execute_code, read_file, append_file]
metadata:
  jros:
    tags: [testing, tdd, red-green-refactor, quality, development]
    category: software-development
    related_skills: [systematic-debugging, node-inspect-debugger]
---

# TEST-DRIVEN DEVELOPMENT

Write the test first. Watch it fail. Write the minimal code to pass.
If you did not watch the test fail, you do not know it tests the right thing.

THE IRON LAW: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
Wrote code before the test? Delete it and start fresh from the tests. Don't keep it as
"reference", don't "adapt" it, don't look at it. Delete means delete.

## WHEN TO USE
Always: new features, bug fixes, refactors, behavior changes.
Exceptions (ask the user FIRST): throwaway prototypes, generated code, config files.
Thinking "skip TDD just this once"? That's rationalization. Stop.

## TOOLS
- Write the test + implementation files with `execute_code` or `terminal` (a heredoc / your
  editor). NOTE: `write_file` only writes the sandboxed skills/ dir, not the target repo —
  use `execute_code`/`terminal` to edit project source.
- `terminal(command="pytest tests/test_x.py::test_name -v")` — run ONE test (RED and GREEN).
- `terminal(command="pytest tests/ -q")` — full suite, check for regressions.
- `read_file(path=…)` — read the code under test.
- `append_file(path="skills/tdd-log.md", text=…)` — offload the cycle when doing many (see STATE).

## STATE OFFLOADING (mandatory for a batch of behaviors)
For 3+ behaviors, log each cycle so you never lose your place:
`append_file(path="skills/tdd-log.md", text="test_name | RED seen | GREEN | refactored")`.

## THE CYCLE

### RED — write ONE failing test
One behavior per test. Clear name describing behavior, not implementation ("and" in the
name → split it). Test REAL code, not mocks (mocks only if truly unavoidable).
```python
def test_retries_failed_operations_3_times():
    attempts = 0
    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3: raise Exception('fail')
        return 'success'
    result = retry_operation(operation)
    assert result == 'success'
    assert attempts == 3
```

### VERIFY RED — watch it fail (MANDATORY, never skip)
`terminal("pytest tests/test_feature.py::test_specific -v")`
Confirm: it FAILS (not errors from a typo), the message is what you expect, and it fails
because the feature is MISSING. Passes immediately? You're testing existing behavior — fix
the test. Errors out? Fix the error, re-run until it fails cleanly.

### GREEN — minimal code
Simplest code that passes, nothing more. No extra logging, no features, no refactoring other
code. Cheating is FINE here: hardcode, copy-paste, duplicate, skip edge cases — REFACTOR fixes it.

### VERIFY GREEN — watch it pass (MANDATORY)
`terminal("pytest tests/test_feature.py::test_specific -v")` then `terminal("pytest tests/ -q")`.
Confirm the test passes, other tests still pass, output is pristine (no errors/warnings).
Test fails? Fix the CODE, not the test. Other tests fail? Fix the regression now.

### REFACTOR — clean up (only after green)
Remove duplication, improve names, extract helpers, simplify. Keep tests green throughout;
add no behavior. Tests break during refactor? Undo immediately, take smaller steps.

### REPEAT
Next failing test for the next behavior. One cycle at a time.

## COMMON RATIONALIZATIONS (all false)
- "Too simple to test" → simple code breaks; the test costs 30 seconds.
- "I'll test after" → tests written after code pass immediately and prove nothing.
- "Tests-after are the same" → tests-after ask "what does this do?"; tests-first ask "what
  SHOULD this do?" and force edge-case discovery.
- "Already manually tested" → ad-hoc, no record, can't re-run.
- "Deleting X hours is wasteful" → sunk cost; keeping unverified code is the real debt.
- "TDD is dogmatic" → TDD is faster than debugging in production.

## RED FLAGS — DELETE CODE, START OVER
Code before test · test after implementation · test passes on first run · can't explain why
the test failed · "keep as reference" · "adapt existing code" · "just this once" · "this is
different because…". All of these mean: delete the code, restart with TDD.

## ERROR HATCH
- Test too hard to write? The design is too coupled — simplify the interface or use
  dependency injection, don't reach for a wall of mocks.
- Bug to fix? First write a failing test that reproduces it, then follow the cycle (pairs with
  the systematic-debugging skill). Never fix a bug without a test.

## DONE WHEN
Every new function has a test, each test was watched failing for the right reason, minimal
code made it pass, the full suite is green with pristine output, and edge cases are covered.
Can't check all of those? You skipped TDD — start over. No exceptions without the user's OK.
