# Foreground outcome truth and combined qualification, 2026-11-08

Fifth isolated increment after `19f573a683cad96ad597309748a61e1f9eb41367`,
preserving all earlier commits on `fix/assistant-core-acceptance-20261108`.
No runtime-Mac changes, default-branch merge, deployment, external provider/account
actions or additional denied GitHub write attempts.

## Confirmed foreground defect

The fourth increment repaired durable background settlement. Its follow-on audit
confirmed the analogous foreground producer defect through actual Gateway
execution, SQLite, the task verifier and event bus, with only the worker/model
step scripted. A fresh partial artifact plus a controller halt could produce a
verified-success TaskCard and done presence. A no-card empty-response halt could
finish as an empty successful reply. The initial probe had **5 failures and
2 passing owner-decision controls**; `blocked` and `needs_owner` already behaved
correctly at card/presence level.

Production controller halt markers include context overflow, stalled execution,
empty response, exhausted reasoning, interruption and errors. They need not have
a separate truthy error field. The old Gateway success check relied on that field
alone, while `close_turn` checked only owner decisions and errors before trying
artifact verification. UI live/recovered state follows the terminal event/receipt,
so repairing the producer is necessary, not changing labels in the UI.

## Bounded repair

- `GatewayTaskOwner.close_turn` rejects a remaining nonempty halt before checking
  artifacts. Explicit blocked/needs-owner, cancellation and unknown-outcome
  branches retain their existing precedence.
- Gateway normalizes actual controller failure halts to its existing failed
  terminal contract, retains partial output and the halt reason, and emits one
  failure event. A no-card failure reports failed presence rather than done.
- Classification occurs before `runtime.finish_turn`; failed controller results
  no longer enter the successful-answer memory/event path. Their partial output
  remains in the canonical failed receipt.
- Blocked, needs-owner and yielded requests retain completed-slice transport
  semantics. Clean completion, cancellation and unknown-effect recovery remain
  unchanged. No new execution, model retry, frontend adapter or scheduler is added.

Important boundary: a foreground turn-owned yielded card is unverified failure,
not a claim of automatic resume. No turn-owned scheduler owns a continuation;
reporting queued/paused would imply resumable work that is not implemented. Durable
background tasks do have that owner and continue explicit yields as verified in
the fourth increment. The actual controller normalizes exhausted durable inner
budgets to yielded. This repair does not implement foreground automatic recovery.

## Focused evidence and review

`dev/tests/jaeger_ai/core/test_gateway_foreground_outcomes.py` contains **20
regression/control cases**. They check card/no-card halt matrices, actual
continuation-controller failures, actual inner-cap-to-yield behavior, owner
decisions, preserved partial output, one worker call, one terminal event, task
cardinality, no false verified world claim and no successful-answer memory entry.
Only the model step is synthetic; Gateway, owner, SQLite and event bus are real.

Independent review found a standalone-test import portability problem in the
first draft. It was corrected to a fully qualified fixture import. Final new-file
standalone run under repository-default importlib mode: **20 passed**, 40 existing
warning instances, 2.71 seconds. Final combined suite: **87 passed**, 122 existing
aiohttp warning instances, 20.65 seconds. The combined run includes existing turn
cards, fourth-increment outcome/recovery tests, single-terminal and follow-up
contracts. Review also checked failure-memory ordering and the explicit
foreground/background yield limitation above.

Use the external headless environment from the baseline report. From the repo:

```sh
python -m pytest -q dev/tests/jaeger_ai/core/test_gateway_foreground_outcomes.py \
  -o cache_dir=/tmp/jaeger-baseline-20261108/foreground-audit/cache
python -m pytest -q \
  dev/tests/jaeger_ai/core/test_gateway_foreground_outcomes.py \
  dev/tests/jaeger_ai/core/test_gateway_turn_card.py \
  dev/tests/jaeger_ai/core/test_task_outcome_precedence.py \
  dev/tests/jaeger_ai/core/test_gateway_single_terminal.py \
  dev/tests/jaeger_ai/core/test_gateway_follow_ups.py \
  -o cache_dir=/tmp/jaeger-baseline-20261108/foreground-audit/cache
```

Logs under `/tmp/jaeger-baseline-20261108/foreground-audit/`:
`before.log`, `main-standalone.log`, `main-combined.log`. The initial probe used
one invented halt label; the final matrix replaces it with actual emitted labels
and an explicit future-unknown-marker control. Earlier external-snapshot logs
are retained but do not replace the final main-checkout results.

## Combined acceptance gates

The final combined source includes the fourth increment's corrected real durable
HTTP fixture: actual write/readback, successful completion-tool receipt and hash,
no halt, one delivery, and no provider replay after restart. Its earlier rejected
completion call and failed aggregate are disclosed in the fourth report, not
erased or counted as passes. Final combined aggregate results follow below.

Counts overlap. No test total should be interpreted as unique tests or complete
product acceptance.

- Focused foreground/new-file: **PASS, 20**; combined scoped backend suite:
  **PASS, 87**.
- Full UI component suite: prior **PASS, 879 tests / 200 files**, retained without
  rerunning because UI source and lockfile are unchanged since the third increment.
- Production UI: same previously built, independently fingerprinted no-mock assets
  at `/tmp/jaeger-baseline-20261108/ui-third/dist`. Fingerprint:
  `f6e4f00489d65292d6c25d21deafe2a77332c8708939c23f288e1bf8bfbd139c`.
- Final repository `scripts/verify.sh`: **PASS, 430 tests** across documented tiers.
- Production-path tier: **PASS, 75**, 17.90 seconds.
- Security tier: **PASS, 203, 2 skipped**, 14.52 seconds.
- Expanded durable/recovery aggregate: **PASS, 104**, 63.45 seconds.
- Root wheel and source archive rebuilt: **PASS**; both independently match final
  owner/Gateway source and the retained no-mock UI fingerprint. Eight unchanged
  companion archives from the third increment are retained byte-for-byte; all
  ten passed archive inspection. No installation or runtime qualification.
- Critical changed-Python lint and whitespace: **PASS**.
- Final full owned HTTP/process aggregate: **PASS, 34 tests, 3 deselected**,
  446.02 seconds. This includes the corrected real durable completion/readback/
  restart journey and authenticated WebUI document journey against retained final
  UI assets. Exclusions remain exactly two browser cases and one AF_UNIX client
  case, not test failures hidden as passes.

## Overall status and remaining gates

Overall product and every visible destination remain **PARTIAL**, using the
[per-tab inventory](assistant-core-ui-20261108.md). Chat and Work now have stronger
truthful-state and recovery evidence, not blanket acceptance. Documents and
Knowledge retain the second increment's scoped evidence and tab/session draft
limits. No other destination is promoted to complete based on these backend tests.

Browser/phone/native-client acceptance remains blocked by this executor's browser
and UNIX-socket limitations. Configured providers, voice/media, external accounts,
native-host operation and user-device layout remain unqualified. The deliberately
headless environment is not a complete media/model installation; broader package
test failures remain documented in the third report. Archive builds do not prove
installed-runtime behavior.

No remote branch, PR or CI exists because the GitHub integration rejected write
access. No alternate write route was attempted after that denial. A cumulative
patch is the review deliverable, not a published or deployed fix. Runtime-local
phone/message work and all user data remain untouched; reconciliation, backups,
full acceptance and separate cutover approval are still required.

Final logs under `/tmp/jaeger-baseline-20261108/`: `verify-fifth.log`,
`production-fifth.log`, `security-fifth.log`, `durable-fifth.log`, `http-fifth.log`,
`packages-fifth.log` and `artifacts-fifth.log`. Earlier passing/failing evidence
remains in the numbered increment reports; current results do not erase it.

Final HTTP reproduction, using the external HOME/venv and disposable state:

```sh
export JAEGER_WEBUI_UI_DIST=/tmp/jaeger-baseline-20261108/ui-third/dist
dev/scripts/run_tests.sh --integration -- --timeout=120 \
  --basetemp=/tmp/jaeger-baseline-20261108/http-fifth \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py \
  dev/tests/jaeger_ai/core/test_webui_document_journey.py \
  -k 'not owned_browser and not attached_client'
```

The independently reviewed implementation scope is qualified by the named gates.
No broader product pass, foreground automatic resume, remote publication or
production deployment follows from those results.
