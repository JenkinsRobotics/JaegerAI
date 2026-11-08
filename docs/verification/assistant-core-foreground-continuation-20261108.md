# Scoped foreground continuation and receipt ownership, 2026-11-08

Sixth isolated increment after `d74c794edf543aa7648aa3e64f1295e58f582029`.
All five preceding commits are preserved. No runtime-Mac changes, merge,
deployment, real provider/account operations or denied GitHub write retries.

## Gap and bounded implementation

The fifth increment made foreground halt outcomes truthful, but a yielded
foreground card had no continuation owner. This increment transfers supported
new cards to the existing durable owner after the original canonical yielded
receipt is durable and its original executor has stopped. It does not introduce
another scheduler, authorization model or execution backend.

- The same card retains its canonical execution, caller, tool grant, native run,
  original result and cancellation root. Deterministic continuation request IDs
  and transactional admission guards prevent competing ticks from dispatching
  duplicate slices.
- A task-specific work-ledger key is selected before the first foreground slice.
  Continuation restores the native trajectory and ledger, not a fresh replay of
  the original request. An intervening chat cannot replace the task's ledger.
- Original Chat Stop reaches transferred work and descendants. Its response
  distinguishes a terminal original slice from still-pending continuation effects.
  Unchanged cancellation reconciliation no longer repeats task-update fanout.
- Current permission checks remain authoritative. Transfer neither grants the
  background-only code-step approval shortcut nor copies spent/session approvals.
- Unknown native effects take precedence over verification, retry, yield and
  cancellation settlement. A crash before the original terminal receipt remains
  unknown rather than replaying accepted effects.
- Each new continuation admission retains its immutable execution and prompt
  contract in the same SQLite transaction. Existing receipts must belong to the
  task session; versioned continuations additionally match the full contract and
  native run/session before binding, dispatch, history, result or cancellation use.
  The exact unstarted admission-before-binding crash window remains recoverable.

### Supported subset

Transfer requires a new versioned canonical snapshot, absolute workspace,
agent/jaeger tier, pinned model and provider, no attachments, and a readable
native owner-run trajectory. The normal UI body (text, request_id and empty
attachment_ids) is covered when session defaults supply the model/provider and
workspace; the server freezes the effective tier at admission.

Historical unversioned cards, unresolved global defaults or workspace,
attachments, worker dispatch, subordinate/background source cards, owner
decisions, unknown outcomes, revoked authority and cancellation are not silently
promoted. This is scoped continuation, not a claim that every Chat will resume.

## Fail-before evidence and review corrections

- Initial new-card probe: two failures and a passing historical-card control.
- A promoted, completed continuation with pending native effects initially paused
  during cancel, then falsely settled cancelled on the next tick. Independent
  review reproduced it. Unknown-effect precedence now survives reconciliation.
- Two recovery assertions found original Chat Stop falsely reported no pending
  work after transfer. The response now includes continuation/descendant outcomes.
- Final review found a separate receipt-ownership issue: a pre-existing completed
  request with the predictable continuation ID, but a foreign session/caller/
  model and no native binding, could be consumed as the task's verified success.
  The external probe observed the foreign output delivered and recorded in task
  history. Six isolated mismatches each reproduced false success: session, tools,
  caller, native binding, task option and display text. A separate ordinary durable
  task also consumed a foreign-session receipt. An admission-window collision
  bound the original native run onto a foreign receipt, and cancellation signalled
  an unrelated colliding request after the initial mismatch was held. These
  require ownership guards at initial lookup, returned admission before binding,
  reconciliation after awaiting a worker, and cancellation. Final corrected results
  are recorded below.

These defects were found before this increment was committed. Earlier passing
aggregate suites did not cover the receipt collision and are not final evidence
for its correction. Fixture corrections are separate from product defects:
initial synthetic completions bypassed the mandatory work-ledger completion
operation, one ledger fixture used stalled rather than yielded, and two recovery
fixtures omitted the supported explicit tier. No safety gate was weakened to
make those fixtures pass.

## Evidence boundaries

The owned HTTP tests exercise ordinary session API defaults, actual native
controller budget yield, restored original tool trajectory and work ledger,
real local write/readback/complete_task SHA-256 receipts, one final parent
delivery, and no provider calls after restart. The model boundary is scripted and
outbound credentials/network effects are excluded. A restricted-tools variant
checks that transfer preserves the exact grant.

Three process-death windows use actual SQLite/effect ledgers and os._exit:
before the canonical original receipt, after receipt before transfer, and after
transfer before continuation admission. Worker effects are disposable local test
effects, not actions against a user's provider or account.

The unchanged UI evidence remains 879 tests across 200 files and the previously
fingerprinted no-mock build from increment three. Source fingerprint:
`f6e4f00489d65292d6c25d21deafe2a77332c8708939c23f288e1bf8bfbd139c`.

## Final qualification

Counts overlap and are not a unique-test or whole-product total. Final corrected
production source hashes are owner `57a30559b1efd22f8a7833f3f17aabac6363283254dc69b37baac92e92625fac`
and Gateway `978334b491e708a5c4f78ced28241cc2a9316805c7b06db7fd6b315f3cf9f420`.

- Combined focused transfer/foreground/durable/race/children/terminal suite:
  **PASS, 200**, 80.29 seconds.
- Standalone transfer controls: **PASS, 62**. Standalone process recovery:
  **PASS, 15**, 40.93 seconds, under repository-default importlib mode.
- Independent external mismatch/race/cancellation matrix: **PASS, 9**, 5.32
  seconds; post-await receipt-corruption check: **PASS, 1**, 2.90 seconds.
  Independent rerun of the 62 transfer controls passed in 9.32 seconds.
- Repository verification: **PASS, 430** across the existing documented tiers.
- Production-path tier: **PASS, 75**, 20.85 seconds.
- Security tier: **PASS, 203, two skipped**, 18.07 seconds.
- Expanded durable/recovery aggregate: **PASS, 181**, 115.73 seconds.
- Root wheel and source archive rebuilt without installation: **PASS**. Both
  independently match final owner/Gateway source and the retained no-mock UI
  fingerprint. Eight unchanged companion archives were retained byte-for-byte;
  all ten pass archive inspection.
- Critical changed-Python lint and whitespace: **PASS**.
- Final full owned HTTP/process aggregate: **PASS, 36 tests, three deselected**,
  520.43 seconds. Exclusions remain exactly two browser cases and one AF_UNIX
  client case imposed by the executor. The final run includes both minimal-Chat
  continuation variants, real durable completion and authenticated document flows.

Pre-correction broad runs passed repository verification (430), production-path
(75), security (203, two skipped), durable/recovery (145), and owned HTTP/process
(36, three excluded infrastructure cases). They remain diagnostic evidence, not
substitutes for the corrected final source checks above.

Logs are under `/tmp/jaeger-baseline-20261108/`. Final aggregate names end in
`-sixth-final.log`; the exact multi-suite runner is `run-sixth-final.sh`.
Focused evidence is under `resume-audit/`: `final-receipt-combined.log`,
`receipt-focused-final.log`, `recovery-receipt.log`, `review-receipt-fixed.log`,
`review-receipt-controls.log`, `review-postawait.log` and
`source-receipt-final.sha256`. Three initial new matrix failures were fixture
foreign-key omissions: the foreign session must exist before deliberately changing
its receipt reference. They are not fail-before production evidence. Earlier
fail-before defect logs remain separately named and retained.

Reproduce using the external HOME/venv/headless configuration from the baseline:

```sh
scripts/verify.sh
dev/scripts/run_tests.sh --production-path -- -n2 --timeout=90
dev/scripts/run_tests.sh --security -- -n2 --timeout=60
python -m pytest -q --timeout=120 \
  dev/tests/jaeger_ai/core/test_foreground_transfer.py \
  dev/tests/jaeger_ai/core/test_foreground_transfer_recovery.py
export JAEGER_WEBUI_UI_DIST=/tmp/jaeger-baseline-20261108/ui-third/dist
dev/scripts/run_tests.sh --integration -- --timeout=120 \
  --basetemp=/tmp/jaeger-baseline-20261108/http-sixth-final \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py \
  dev/tests/jaeger_ai/core/test_webui_document_journey.py \
  -k 'not owned_browser and not attached_client'
```

The bundled runner records the exact expanded durable aggregate, external state,
cache locations and archive build command. No command targets the runtime Mac.

## Remaining acceptance

Overall product and every visible destination remain **PARTIAL** under the
[per-tab inventory](assistant-core-ui-20261108.md). Chat and Work now have scoped
continuation evidence; no other destination becomes accepted by inference.
Browser/phone/native-host, configured providers, voice/media and external-account
journeys remain unqualified. The headless package/IPC limitations in the earlier
reports remain. Archive inspection is not installed-runtime qualification.

The versioned subset above intentionally excludes unresolved defaults and
historical work rather than manufacturing authority. Documents retain same-tab/
session draft limits and unknown creation-outcome limitations. No new evolution
framework or permanent authority is introduced.

No remote branch, PR or CI exists because repository write access was denied.
No alternate write route was attempted afterward. The cumulative patch is a
review artifact, not a published or deployed fix. Runtime-local work and user
data remain untouched. Reconciliation, backups, full acceptance and separate
cutover approval remain necessary.

## Later ordinary Chat default admission

The [eighth increment](assistant-core-default-admission-20261108.md) supplies
canonical execution facts for supported ordinary new-chat defaults, preserving
instance workspace mode rather than converting it into a project. The original
new-card, checkpoint and authority restrictions remain. Historical receipts,
unsupported routes and queue admission are not broadened by that repair.
