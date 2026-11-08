# Specialist skill scope lifetime, 2026-11-08

## Actual defect and bounded producer repair

A real no-selector chat can be routed to a specialist by the existing router.
That path imported nonexistent bind_skill_scope and failed before execution.
The canonical jaeger-agent skill_scope context manager already existed. The
Gateway now uses it for the complete specialist preparation/execution lifetime,
including asynchronous work submitted to a thread, and restores the surrounding
scope on normal return, error and cancellation. No new setter, no-op shim,
framework or package dependency is introduced.

The existing caller, frozen allowed-tool intersection, specialist skills and
policy-kernel authority remain. Empty assigned skill sets remain restrictive.
Cancellation of the awaiting task restores its context without widening an
already-running thread's copied restricted context.

The execution body was extracted into a helper so the context manager covers
all exits. Composition with lead recovery initially omitted identity_error and
session_agent_id; combined tests caught both. Both values are now explicitly
transferred. Independent AST/symbol-table review confirmed the original execution
and cleanup tail is unchanged, including nested closure references and identity
refusal before effects. Superseded candidates and failures remain preserved.

## Qualification

- Fail-before: all four initial scope regressions failed with the missing-symbol
  ImportError. A fifth test later covered cancellation during the worker thread.
- Final composition on the exact selected-agent/lead-recovery base: 174 focused
  tests passed, including full journal/identity/selection and specialist controls.
- Independent final scope/journal suite: 139 passed. Three further independent
  controls cover failure settlement, preparation cancellation without dispatch,
  and specialist-to-ordinary isolation within the same asyncio task.
- Actual unshimmed no-selector HTTP creation -> calendar routing -> Entity OWNER
  execution passed on both builder and independent reviewer. The model attempted
  a forbidden file write; the original caller and restrictive grant remained,
  no file was created and no permission expansion was requested.
- Hygiene9 passed; whitespace and critical lint passed. Main integration compared
  server.py byte-for-byte with reviewed candidate 2c9e326b94195b579d675e23ac42e53e57141eea,
  SHA-256 770d9e22e3a5cd2bdfc0bd2461eecb9efb066ce6899595d4465c06a578e0d7d2.

Counts overlap. Exact commands/logs and independent controls accompany the review
artifact. The diagnostic shim used earlier to isolate the lead-routing regression
is not used in this repair or its actual OWNER integration. An initial main lint
command named a nonexistent test file; the corrected command checked the actual
scope and OWNER test files successfully.

## Limits

The provider/model and peripheral inventory are scripted. The Gateway, routing,
resident owner, skill-scope boundary and denial are real. This does not establish
calendar-account access, fetched calendar data, rendered UI/phone behavior or
parity with external assistants. It does not certify an unknown effect as stopped.
Full combined main build/HTTP/process gates follow separately. No production
runtime change, live provider/account, publication, merge or deployment occurred.
Overall and per-tab acceptance remain PARTIAL.

See the later [combined qualification](assistant-core-combined-qualification-20261108.md) for final integrated gates. The scoped candidate results above are not substituted for those gates.
