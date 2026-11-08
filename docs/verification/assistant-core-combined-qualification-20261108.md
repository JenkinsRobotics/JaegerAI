# Combined assistant-core qualification, 2026-11-08

## Candidate and boundaries

The isolated branch preserves twenty-three commits over review base
ff71bb769bc56e4c6d7be6d540a86be73e291e07. The last four increments add
real default-report delivery qualification and provider settings preservation,
type validation and concurrent-save protection. The separately inspected latest
master adds only two CI/documentation commits; see the
[upstream check](assistant-core-upstream-check-20261108.md). No combined upstream
revision was executed. The final source is identified by its frozen Python manifest. The bundle README and
commits.txt identify its final commit/tree and cumulative patch hash.

No runtime machine edit, build, restart, installation or deployment took place.
No merge occurred. GitHub writes remain blocked; there is no remote branch, PR
or CI. The prepared draft is text only. All operator data and dirty runtime work
remain preserved outside this isolated checkout.

## Combined final results

- Repository verification: 430 passed; production-path: 75 passed.
- Security: 203 passed, with 2 platform skips.
- Durable/recovery/artifact: 558 passed; agent runtime/commitment: 120 passed.
- Owned HTTP/process: 51 passed, 3 established infrastructure exclusions,
  654.54 seconds. This includes all four strengthened SIGKILL/two-restart cases
  and the real default-report delivery journey.
- Separate real unshimmed specialist OWNER integration: 1 passed.
- Provider settings: 80 passed. Independent final transaction review: 89 passed,
  5 VS Code tests excluded, plus 9 hygiene checks. The main 80-case gate includes
  the safe synthetic bridge controls. No real provider credentials were used.
- Independent final artifact review: 97 passed; retry review: 9 new controls
  and 66 existing controls passed. Counts overlap with other evidence.
- Unchanged UI: prior 910 tests / 201 files, theme/TypeScript/production/no-mock
  build reused after independently matching 866 source files and 857 manifest
  inputs. Source fingerprint:
  `36612489016ec2283f86dcc22d435be6aa80478591ab9dcb4551833c7be0fc1f`.
- Root and jaeger-agent wheel/source archives rebuilt without installation;
  six unchanged companions retained; all 10 archives inspected. Twelve root and
  five agent runtime modules match source byte-for-byte, with matching UI
  provenance. Critical lint, source freeze and whitespace checks pass.

All tests use external state, cache and temporary directories. The final Python
source SHA-256 manifest was checked after testing. Critical Python lint and git
diff --check pass. Test counts overlap; this is not the complete package matrix.
Existing warnings and the two platform skips remain visible in raw logs.

## Acceptance journey covered

- Real authenticated local WebUI/Gateway HTTP: conversation admission, incremental
  stream, cancellation, persisted transcript, SSE replay and restart.
- Real managed document CRUD, revision conflicts, search/reopen and persistence;
  memory remember/recall/correction/forget across restart.
- Real approval decisions and file writes, durable work ledger, readback and
  verified completion; foreground transfer, queue defaults, scheduled execution,
  cancellation propagation and request/session collision rejection.
- Actual top-level agent selection and immutable retry behavior; stable home,
  explicit pinned lead and route-checked fresh admission proof.
- Real unshimmed specialist OWNER autorouting under canonical skill scope, with
  preserved caller and a denied out-of-grant write, no file and no new approval.
- Four real owned-child SIGKILL cases at the whole-request seal boundary. Safe
  sealed proof projects once and runs queued work once; pre-seal loss and
  authority/session drift remain unknown and keep queued work paused. Both
  subsequent restarts check original status, bytes/mtime, provider/tool/effect
  counts, all-session terminal projection and queue state. No blind replay.

The model/provider boundary and nominated fault barrier are scripted. Controllers,
SQLite journals, task verification, approval and file tools are not fabricated.
The actual HTTP proxy is not a rendered browser or physical device. The existing
HTTP fixture deliberately disables optional skill smoke subprocesses; production
defaults remain unchanged. This does not qualify cold production skill startup or
non-core missing-smoke gates.

## What changed after the thirteen-commit bundle

1. [Selected agents](assistant-core-chat-agent-selection-20261108.md): creation
   previously ignored the UI selector and silently assigned the lead. Canonical
   validation/pinning and immutable retries now preserve the requested agent and
   reject conflicting or unauthorized identity claims.
2. [Default lead identity](assistant-core-default-lead-journal-20261108.md): fresh
   stable/pinned/home lead requests bind immutable server-selected identity to
   request proof. Unpinned first-turn routing remains intact and unqualified until
   the route commits. Registry drift and invalid identity fail closed.
3. [Specialist scope](assistant-core-specialist-scope-20261108.md): the branch
   imported a nonexistent binder. It now uses the existing canonical context
   manager through preparation/execution and thread context, restoring parent
   scope without expanding tools, caller authority or allowed skills.
4. [Actual process loss](assistant-core-owner-process-loss-20261108.md): test-only
   request/session/PID-scoped fault hooks enable real kill/restart qualification
   without signaling unrelated processes or weakening the verified TaskCard gate.

5. [Default artifact scope](assistant-core-artifact-default-scope-20261108.md):
   verified default-workspace reports can be cataloged and reopened using an
   owner-captured checked root/path, unchanged originating session mode and
   current instance scope. Untrusted metadata is discarded; file identity and
   bytes are checked without granting access to old unproved receipts.
6. [Retry identity](assistant-core-retry-identity-20261108.md): markerless retries
   cannot acquire fresh lead proof from current routing. Qualified retries retain
   identity-drift refusal, and separate fresh admissions still qualify normally.

## Preserved combined failure and independent correction

The seventeenth combined source passed 49 HTTP cases and failed the existing
immutable retry equality assertion, with 3 exclusions. Its four strengthened
process-loss cases passed. That failed log remains http-seventeenth-final.log;
its source and other passing gate logs remain preserved. The nineteenth run
then passed 50 HTTP cases, with 3 exclusions, after the producer correction.
Those logs remain included separately. The latest twenty-third run above
reruns the combined source and adds the new report journey.

Independent review also rejected the initial default-artifact patch: it could
hash a file under root A, then re-resolve a worker path and issue trusted metadata
for root B. The corrected producer captures one root and returns exactly checked
paths. The initial failed controls and corrected 97-case independent review are
included, with no change to current scope or digest enforcement.

## Remaining acceptance

Overall and every tab remain **PARTIAL**. Browser/phone layout and interaction,
actual configured provider/account quality, native-host permissions, voice/media,
and actual native-bridge restart remain unqualified. Chromium and AF_UNIX are
blocked here; missing optional packages prevent a full package-suite pass.

Proof applies only to the documented admitted paths. Historical markerless
identity can be ambiguous. Other named agents, unsupported background or yielded
paths, attachments and unresolved defaults do not gain sealed recovery. Registry
files and SQLite are not one atomic cross-store transaction. Missing proof may
leave a blocked session safely. Existing continuation still requires a versioned
new card, canonical workspace/model/provider and readable checkpoint. Unsaved
document drafts are limited to the same tab/session.

The [per-tab audit](assistant-core-ui-20261108.md) inventories the actual UI;
source-backed capabilities and component tests are not proof that every tab works
with a real account. Package/archive matching is not installation acceptance.
Runtime phone/message work is not automatically reconciled into this branch.
Separate data-preserving reconciliation and explicit deployment approval remain
necessary. Evolution work is still deferred.

## Evidence and reproduction

The bundle includes run-twentythird-final.sh and per-gate logs, source hashes,
artifact inspection, machine-readable UI results, and independent review logs.
Invoke each runner case from the isolated clone with its recorded external venv,
and select a fresh external basetemp for every rerun. Do not reuse pytest basetemp
paths containing retained evidence, since pytest clears them.

Earlier failures remain included: concurrent commitment activation, initial
bridge cancellation, selected-agent/default inference, rejected identity marker
candidates, and process-fixture prompt/event-contract errors. The historical
four-case process result used fewer assertions. Only the final combined run
qualifies the strengthened two-restart checks. No prior failure is relabeled a
pass and no test deadline or safety boundary was weakened to obtain these results.

## Default-report journey and Settings corrections

The [default report delivery test](assistant-core-default-report-delivery-20261108.md)
adds actual default-mode task/approval/tool/artifact HTTP acceptance, authenticated
download, restart/replay identity and scope-drift denial. That twentieth increment changed no production bytes. Its first integrated run
passed separately, as did a fresh 430-check repository verification. It is now
also included in the actual 51-case final run above. Research source support
remains distinct from artifact-byte proof: ordinary research completion does
not automatically enforce the existing grounded-citations procedure.

The next three increments fix provider [read preservation](assistant-core-provider-settings-preservation-20261108.md),
[input types](assistant-core-provider-settings-validation-20261108.md), and
[revision-bound concurrent saves](assistant-core-provider-settings-transaction-20261108.md).
They preserve unrelated values and modes, expose conflicts without retry, and
distinguish an uncertain postcommit result from a confirmed save. Cooperating
writers require the same canonical lock/state root. A noncooperating writer can
still race after the final check, and no new frontend stale-form contract was added.
