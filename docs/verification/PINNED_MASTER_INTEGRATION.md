# Pinned master integration review contract

This review branch preserves the saved version16 handoff (`fb66402`), the
reviewed Agents outcome repair (`23e6c84`), and canonical master pinned at
`3926eedd353faaf9ddd54eecf74a9f6fbd003707`. It does not follow a moving upstream
head. The merge parents and all intermediate commits remain available.
The saved version16 handoff is not replaced by this source integration.

## Returned controller failures

Both histories prohibit recording an interrupted or stalled controller as a
successful answer. The integrated Gateway classifies a normally returned
non-owner/non-yield halt through its terminal-outcome path, after settled-run
checks. It retains diagnostic text and seals a known failed owner receipt.
It must not convert that returned halt into an exception before the receipt
transaction: that would discard diagnostics and turn a known failed return
into an unconfirmed outcome. Genuine execution exceptions and uncertain effects
retain their separate conservative handling.

`test_gateway_single_terminal.py` covers stalled failure with one terminal,
one worker invocation and no successful memory finalization.
`test_gateway_foreground_outcomes.py` covers returned controller failures,
owner decisions and bounded yields. `test_owner_request_journal.py` checks
failed receipt preservation and native/owner identity, authority, cancellation
and transfer boundaries. Failed diagnostic output is not a successful answer.

## Test-instance isolation

A real runtime boot in `test_gateway_durability.py` binds a process-wide
pipeline layout. Its fixture now restores that binding at teardown alongside
the runtime and resident state. Otherwise a later synthetic instance can read
a preceding fixture's completed work ledger despite using its own state root.
Production bound-layout precedence is unchanged.

The held merge baseline `72a3ecb` retains the original conflict resolution and
upstream stalled regression. Its initial combined focused run had 317 passes
and 52 failures. The returned-halt contract reconciliation addressed three
failures; restoring the fixture's layout binding addressed the remaining 49
order-dependent failures. The same 369-case order subsequently passed. Those
initial failures remain part of the review history, not retroactive passes.

## Steering and client truth

Steering identity must bind the exact session, request and text before live
injection. A retry or restart must not replay a delivery whose outcome is
uncertain, and a reservation is not an acceptance receipt. Existing durable
steering receipts remain readable without inventing historical authority.
The steering regression suite exercises duplicate admission and failure
boundaries with synthetic agents rather than live providers.

Voice capability failures must leave loading state and invalidate stale
availability, including a failed refresh after a successful check. Audio
preference persistence is separate from capability-probe success. Approval
resolution must clear only its correlated confirmation/tool waiting state;
it must not declare tool execution successful or clear an unrelated approval.
The UI tests cover these distinctions alongside reconciliation and reported
Agents outcomes.

## Qualification boundaries

The required final checks include the repository `scripts/verify.sh` pipeline,
production-path and security tiers in `dev/scripts/run_tests.sh`, relevant
owner/background lifecycle, migration, cancellation, process-loss and HTTP
suites, and the Agents publisher/bridge/backlog contracts. Upstream steering,
voice and approval/activity tests must run with the preserved recovery tests.

The shared UI must be built outside the source tree with the exact committed
inputs and matching existing dependency lock. Component qualification uses
`npm test -- --maxWorkers=2`; the production build includes theme checks,
TypeScript, Vite and no-mock verification. Package inspection must compare the
embedded production UI bytes and all affected packaged source files. Companion
archives may be reused only after unchanged package-tree/input and archive-hash
verification.

Synthetic providers/effects and temporary isolated stores do not establish live
provider, native microphone/speaker, browser, phone or Mac runtime acceptance.
No push, default-branch merge, installation or deployment is part of this review.
