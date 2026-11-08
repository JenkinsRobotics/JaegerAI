# New-chat selected agent, 2026-11-08

## Defect and repair

The actual UI sends top-level agent_id when creating a chat. The Gateway creation
handler ignored that selector, then archive_on_create assigned native:jaeger.
Selecting another agent therefore silently started the lead instead. An initial
store-only inference incorrectly described the outcome as unassigned; exercising
the complete handler exposed the default-assignment hook and corrected it.

The handler now resolves explicit and legacy metadata selectors through the
canonical registry, validates the same caller scope/session-prefix access used
by agent home, and rejects conflicting, unknown or disabled selections. Aliases
resolve to the canonical identity. Explicit selection is pinned so automatic
routing cannot replace it; no-selection requests retain existing lead behavior.
Client-provided role, kind or permission claims cannot replace registry authority.

Idempotent creation of an existing session returns its existing persisted row
without merging new metadata or changing its history. A different selected
identity, including an attempt to claim a historical unassigned chat, returns
409. Existing archived state, metadata, timestamps and messages are preserved.

The old metadata:null-as-empty behavior is retained for both default and selected
agents. The first candidate unnecessarily tightened this to400; that was corrected
before integration. Invalid non-object metadata and invalid/null selectors are
rejected without creating a chat. No model/provider/tool permission is expanded.

## Qualification

- Fail-before against the unmodified handler:21 failures and one default-lead
  control pass. Actual responses selected native:jaeger instead of native:selected.
- Corrected isolated scope:116 tests passed, including25 new selection cases,
  existing default-admission, operator continuity, session hygiene and registry.
- Independent final review:21 additional handler controls passed, including
  archived retries, null compatibility, aliases/conflicts and caller-prefix denial.
- A real local HTTP check uses production authentication middleware and routes
  for POST creation, GET detail and filtered listing. Unauthenticated and restricted
  callers are denied. Daemon startup is suppressed in that narrow HTTP test;
  it does not claim real provider or agent-turn execution.
- Merged main checks: repository verification430; production75; security203 with
  two skips; durable/recovery427. All passed. Critical lint and whitespace passed.
  Source hashes were checked before commit. Counts overlap.

Exact final runner and logs are preserved as run-fourteenth-final.sh and the
fourteenth-final gate logs in the cumulative evidence. Existing private test
state and caches are outside the source tree. No runtime Mac operations,
credentials, remote write, merge or deployment were used.

## Remaining acceptance

This is backend selection qualification, not rendered browser/phone testing or
model execution by every selectable agent. Raw malformed JSON can still follow
the preexisting request.json exception path and return500. General corrupted
registry behavior is not newly qualified by these typed-selector controls.

The default-lead request-identity/recovery increment remains separate. Full owned
HTTP and rebuilt-archive qualification for the combined next candidate must be
rerun; the preceding43-test HTTP result belongs to the thirteen-commit snapshot,
not this changed creation handler. Overall and per-tab acceptance stay PARTIAL.

The subsequent [default-lead journal increment](assistant-core-default-lead-journal-20261108.md)
uses this exact pinned-selection behavior and separately qualifies fresh stable
lead identity. It does not turn other selected agents into journal-qualified leads.
