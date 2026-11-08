# Default-workspace artifact visibility, 2026-11-08

Scope: isolated development clone based on `35100a1e477a5eaebc21cd4fc66f3f25b530f015`.
No Mac runtime changes, deployment, remote writes, providers, or owned-process fixtures.

## Defect and reachable path

ResearchPage proposes via `POST /v1/tasks` using the selected agent's home session.
`handle_tasks` preserves the parent's empty workspace. GatewayTaskOwner verifies
work-ledger file receipts using the effective instance workspace, then records
`completed_verified`. However, `tasks.artifacts.references` returned no references
when the admitted execution workspace was empty. Pinned foreground defaults also
failed reopening because the originating session intentionally has no project.
Library, Research and Work share this catalog; a verified report could disappear
or show unavailable even while its bytes and originating authority remained intact.

Three deterministic regression cases fail against unchanged base source:
research default, pinned instance default and owner-discovered named file.
These use real SQLite admission/storage, owner verification and artifact projection;
only the instance workspace binding is substituted. No provider output is claimed.

## Repair at the verification producer

`GatewayTaskOwner.verify` keeps its `(verified, evidence)` API. After successful
independent file checks it reissues canonical `owner_file_sha256` receipts, keeping
only the owner-resolved path and checked digest. For instance mode it adds an
owner-generated versioned scope with the checked workspace. Worker extra fields
are discarded, including any purported owner scope. The file checker
is extracted into `_verify_files` and returns the exact checked paths. Verification
captures one root for checking and receipt emission; it does not resolve worker
paths or discover instance scope again after hashing.

Artifact projection accepts the new scope only on `owner_file_sha256`. The older
worker `file_sha256` receipts could contain arbitrary keys, so even a fabricated
scope on that older kind cannot grant default-workspace access. Workers cannot
submit an owner receipt kind through verification: the checker accepts only
worker `file_sha256` and constructs named-file evidence itself. Normal task
create/edit APIs do not write supplied verification, payload or terminal state.

Current instance root and originating session mode must still match the saved
scope before bytes are read. The shared digest-checking reader receives a
read-only session projection for that checked root. No stored session/project,
upload, runtime configuration, permissions or file ownership changes. Paths and
internal scope remain absent from the public artifact catalog. Explicit-project
artifacts keep their existing access checks. Historical default artifacts lacking
owner scope are not retroactively granted access or reverified.

This is provenance in the trusted owner store, not a cryptographic defense
against arbitrary direct database modification. Inconsistent receipt digest,
path or scope is rejected; a malicious actor rewriting all trusted database
fields is outside the existing local owner-store trust boundary.

## Checks

- The three positive regression cases fail before the patch.
- 26 new deterministic tests cover reopening after store recovery, default/pinned/
  named receipts, root drift, project-mode change, missing origin/runtime,
  symlink escape, changed bytes, forged worker scope, legacy receipt injection,
  explicit-project compatibility and inconsistent saved receipts.
- Producer controls exercise close_turn with forged owner receipts and failed,
  cancelled, yielded, blocked, needs-owner and unknown outcomes. None publishes
  artifact access. Actual task create/edit handlers ignore forged verification;
  client `_instance_defaults` is rejected.
- Existing artifact HTTP and task/turn-card tests are rerun separately with the
  same isolated state. No full daemon, browser, native host, or provider acceptance
  is inferred. Overall Research/Library/Work acceptance remains PARTIAL.

External evidence directory: `/workspace/shared/research-artifact-audit-20261108/`.
`fail-before-final.log` records 3 failures against base; `final-tests.log` records
the final focused aggregate. The coordinating task owns independent review and
repository-wide verification.

## Independent-review correction

The initial frozen patch recomputed instance scope after verification and could
mislabel an A-root receipt as a B-root receipt if binding changed between calls.
A second raw-path resolution could also follow a changed worker symlink after
hashing. The revised producer captures one root and emits the verifier's exact
resolved paths. Three new tests (worker-root drift, named-root drift, post-hash
symlink change) fail on the initial patch and pass after correction.

The original patch and logs remain retained. `race-fail-before.log` records the
three failures; `revised-final-tests.log` records the revised aggregate, including
the independent reviewer's root-drift and descriptor-reader controls.

## Integrated scoped checks

The corrected patch SHA-256 is
6b03298dcf128a9e820edb964289c976ffea7cd485fc3e3d46c8252cdde1ec5a.
Independent final review passed 97 checks, including the original failing race
and six additional fail-closed controls. Integrated main source matches both
reviewed production files byte-for-byte. Its artifact, owner and turn-card
aggregate passed 89 tests in 18.96 seconds; counts overlap with other suites.
Full combined gates are recorded separately in the combined qualification report.

The subsequent [combined qualification](assistant-core-combined-qualification-20261108.md)
passes the expanded 558-case durable/artifact gate and all 50 selected owned
HTTP cases. A separate default-report full-process catalog/download journey is
not inferred from these verifier/handler controls.

The subsequent [default report delivery test](assistant-core-default-report-delivery-20261108.md)
qualifies the additional real owned HTTP path for default-mode execution,
authorized report download, restart/replay and scope-drift denial. It is test-only
and does not convert artifact verification into citation-support verification.
