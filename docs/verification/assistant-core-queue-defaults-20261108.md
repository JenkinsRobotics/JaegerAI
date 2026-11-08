# Queued Chat default snapshots, 2026-11-08

Ninth isolated increment after `c26b38e1ec122c2f2e3561565b095a6bb9e9bb88`.
The preceding eight commits remain intact. No runtime edits, installation,
restart, default-branch merge, deployment or denied GitHub write retry.

## Confirmed Queue next gap

Ordinary new Chat now freezes supported server defaults before execution, but
its Queue next handler called a separate admission producer without that resolver.
A minimal queued message therefore retained `model=None`, `provider=None` and an
empty workspace. Promotion correctly preserved the receipt, but runtime then
resolved later defaults and the existing foreground owner could not mark the
request eligible for safe continuation.

An external regression produced three failures with six passing controls:
missing default snapshot, absent continuation ownership and no workspace-drift
rejection. Explicit request/session settings, caller identity, exact tool grants,
replay and promotion controls passed. This is a producer defect, not a reason to
rewrite old receipts at promotion.

## Bounded repair

Only two production files change. Immediate and queued admission share the same
fresh-default helper; the queue handler supplies the existing server resolver.
The helper runs inside the admission transaction, after receipt/session identity,
replay, capacity and attachment checks. Requested choices and their fingerprint,
session metadata/revision, caller and tool authority are not changed.

Supported instance-mode workspace and route fingerprints are frozen at enqueue.
Promotion and replay use that snapshot, never current defaults. Historical
incomplete queued rows remain incomplete and conservative. Callback exceptions
roll back admission; rejected or replayed work does not invoke the resolver.
The eighth increment's canonical inheritance and drift checks remain unchanged.

## Focused and independent evidence

- Three fail-before regressions and six passing controls retained.
- Ordinary defaults, queued defaults and existing session queue suite: 75 passed.
- Independent suite: 82 passed, including seven additional rollback, rejection
  ordering, digest preservation, concurrent replay and custom-runtime controls.
- Actual owned HTTP Queue next uses a real running turn as a blocker, admits a
  minimal queued message, checks its durable snapshot and replay before release,
  and lets production queue promotion and native execution proceed.
- The continuation journey reuses original task, native checkpoint and ledger
  identity checks, exact caller/tools, verified completion, receipt, restart and
  no-repeat delivery checks. The bare-file journey verifies real write/readback,
  completed ledger and SHA-256 evidence at the instance skills destination, with
  no file at the explicit-workspace destination.

Review caught a proof gap: a stream reader ending at its first terminal event
cannot prove no duplicate terminal events. The retained tests inspect complete
persisted event history instead, including after replay/restart. The first HTTP
run then passed seven cases and failed one new setup assertion: the trivial
blocker correctly created no durable TaskCard, so expecting two cards was wrong.
The original stronger single-card invariant was restored. Both new queued cases
then passed, with exact single terminal events also required for the blocker,
queued original and resumed child. The failed run is retained rather than erased.

The corrected eight-case owned HTTP selection passed in 112.92 seconds before
integration. The patch applied cleanly after the eighth commit, and all five
source hashes matched. Final main-source gates:

- Repository verification: **PASS, 430**.
- Production-path: **PASS, 75**, 20.50 seconds.
- Security: **PASS, 203**, two platform skips, 16.56 seconds.
- Durable/recovery aggregate: **PASS, 275**, 121.75 seconds.
- Independent queued/default controls rerun on main: **PASS, 82**, 18.40 seconds.
- Owned HTTP/process aggregate: **PASS, 43**, 455.03 seconds, with the three
  existing browser/attached-client infrastructure exclusions.
- Critical Python lint and diff whitespace: **PASS**.
- Root wheel and sdist rebuilt. Eight unchanged companion archives retained;
  all ten inspected. Six root runtime modules and both agent runtime modules
  byte-match source. No package was installed into a runtime.

The five-file manifest SHA-256 is
`58382f4d3b6f424b5ed993729bf89cc6ca0dc25d217551f2290e755f7fd4948f`.
Hashes remained unchanged after tests. The no-mock UI build and its earlier
879 tests in 200 files remain unchanged, with source fingerprint
`f6e4f00489d65292d6c25d21deafe2a77332c8708939c23f288e1bf8bfbd139c`.
Counts overlap; prior candidate results are not added to final totals.

The review bundle includes `run-ninth-final.sh`, selected final/failure logs,
independent control tests and review notes. Use its `verify`, `production`,
`security`, `durable`, `http`, and `packages` gates with disposable external
HOME/state/cache and Python 3.12. The exact expanded durable targets are in that
runner. `inspect-final-distributions.py` compares the changed runtime members and
UI provenance; the committed release-archive inspector checks all packages.
Earlier headless environment and skill-smoke exclusions remain explicit.

## Acceptance boundaries

The owned HTTP provider boundary is scripted. Optional skill smoke subprocesses
are disabled under the explicitly documented seventh-increment fixture profile;
production defaults remain unchanged. Real admission, tools, approvals, native
checkpoints, ledgers and receipts are exercised, not replaced by result mocks.
Browser, phone, native-host, real-provider and installed-runtime acceptance remain
unqualified. All product and per-tab states remain **PARTIAL**.

A subsequent isolated audit found a separate gap: confirmed native reconciliation
can settle recovered unknown work without draining an eligible queued successor.
Late historical settlement can also overwrite newer session status. That repair
is outside this ninth increment and is not implied by the passing queue journeys.

Unsupported route aliases, unresolved defaults, old receipts and attachment
continuation limits remain conservative. There is no new scheduler, authority
model or evolution framework. Runtime-local work and all user data are preserved.
The patch is a review candidate, not a remote PR or deployed fix. Reconciliation,
backups, full acceptance and separate cutover approval are still required.
