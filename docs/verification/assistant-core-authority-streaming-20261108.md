# Assistant-core authority and streaming repair, 2026-11-08

Third isolated implementation increment after `f4f05ed55281d3abf453b737234ced79a2b9423b`,
on `fix/assistant-core-acceptance-20261108`. The previous two commits are preserved.
No runtime-Mac changes, production credentials, external provider execution,
merge, deployment or further denied GitHub write attempt.

## Reproduced failures and repairs

### Streaming must not lose authority events

Malformed JSON inside a complete SSE frame previously became a raw-string event.
The shared Gateway client could then advance its reconnect cursor while losing
the event's request identity and contents. A real loopback HTTP producer, native
fetch, production GatewayClient and followTurn reproduced a missing approval
after reconnect. The decoder now rejects that frame before publishing its cursor.
It reports only a generic error and diagnostic category/ID, never raw content.
Valid JSON-string payloads remain supported.

The HTTP regressions cover a malformed framed event, an ordinary partial-EOF
control, and a partial upstream frame followed by a proxy-style in-band error.
The recovered stream delivers the approval. Persistent corruption ends as
unknown after exactly three GET attempts with the same trusted cursor. It never
resubmits the turn or claims successful execution. Component tests do not replace
an actual browser or native-client acceptance test.

### Every decision adapter must enforce saved authority

The legacy approval HTTP route could accept an expired saved proposal before an
inbox read happened to sweep it. It also accepted a persistent `always` choice
that the current tool approval card did not offer. Both regressions succeeded
where the test expected HTTP409 before repair.

The existing SQLite decision transaction now validates deadline and offered
scope for affirmative decisions under the write lock. It recomputes time after
lock acquisition, so contention cannot extend a deadline. Invalid or non-finite
declared deadlines fail closed; explicit keep-on-expiry remains supported.
Negative settlement can still close a pending row. `allow`/`yes` aliases mean
once on both the choice and offered-option sides; the original saved answer is
preserved. An explicitly offered legacy persistent choice still works.

Two timeout races were separately reproduced. A committed `changes` or
`cancelled` answer was treated as positive by an exclusion-based fallback. An
affirmative receipt followed by cancellation of the real execution scope could
also authorize the provider. The fallback now requires an explicit affirmative
decision and a non-cancelled live scope. Cancellation does not rewrite an earlier
immutable decision receipt, but it still prevents execution when observed there.

Real owned Gateway tests prove expired decisions remain refused across restart,
without task authorization, run history or provider invocation. Current-card
scope escalation leaves the approval pending and a subsequent legitimate denial
works. SQLite lock-contention and simultaneous decision tests check transaction
boundaries and first-writer behavior. These are synthetic local effects and a
scripted provider, not external-account or live-provider qualification.

## Reproduction and evidence

Use the external headless environment documented in
[the baseline](assistant-core-baseline-20261108.md). Keep HOME, state, caches,
builds and subprocess artifacts outside the source tree.

Focused authority suite from the repository root:

```sh
HOME=/tmp/jaeger-approval-audit/home \
JAEGER_STATE_DIR=/tmp/jaeger-approval-audit/state \
JAEGER_NO_ATTACH=1 JAEGER_TEST_HEADLESS=1 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPYCACHEPREFIX=/tmp/jaeger-approval-audit/pycache \
/tmp/jaeger-baseline-20261108/venv/bin/python -m pytest \
  dev/tests/jaeger_ai/core/test_gateway_approval_expiry.py \
  dev/tests/jaeger_ai/core/test_gateway_approval_expiry_contract.py \
  dev/tests/jaeger_ai/core/test_recovered_approval_context.py \
  dev/tests/jaeger_ai/core/test_approvals_inbox_push.py \
  dev/tests/jaeger_ai/core/test_durable_tasks.py -q \
  -o cache_dir=/tmp/jaeger-approval-audit/pytest \
  --basetemp=/tmp/jaeger-approval-audit/cancel-after
```

Final result: **65 passed**, 60 existing warning instances, 38.38 seconds.
Log: `/tmp/jaeger-approval-audit/cancel-after.log`. Late cancellation fail-before
log: `/tmp/jaeger-approval-audit/cancel-before-real.log`. The earlier expired,
unoffered-scope and negative-timeout failures were captured in tool output, with
owned fixture artifacts under `before/`, `scope-before/` and `negative-before/`
in that directory; no nonexistent saved log is claimed.

The new UI regression is `src/api/sseRecovery.http.test.ts`. Run the full UI suite
from an external UI snapshot with the committed lockfile, `npm ci`, then
`npm test -- --maxWorkers=2`. Full result: **879 tests in 200 files passed**.
Log and machine-readable results: `/tmp/jaeger-baseline-20261108/ui-third-tests/`.

Fresh production UI build: `/tmp/jaeger-baseline-20261108/ui-third/dist`.
The source fingerprint was independently recomputed from the current checkout
and matches `build.json`, with `mock=false`:
`f6e4f00489d65292d6c25d21deafe2a77332c8708939c23f288e1bf8bfbd139c`.
Index SHA-256:
`cb56ba652f446a54923f83989f900d8838303403fd01bb1206ca5e9fbfbddaf0`.
Build snapshot: `/tmp/jaeger-baseline-20261108/ui-third/build-9db70q25/ui`.

## Integrated gates

Counts overlap and must not be added as unique tests.

- Full UI suite: **PASS, 879 tests / 200 files**.
- External production UI build: **PASS**, theme, TypeScript, Vite, no-mock;
  existing bundle-size warning retained.
- Repository `scripts/verify.sh`: **PASS, 430 tests** across documented tiers.
- Production-path tier: **PASS, 75 tests**, 21.92 seconds.
- Security tier: **PASS, 203 tests, 2 skipped**, 12.83 seconds.
- Durable/recovery aggregate: **PASS, 81 tests**, 49.32 seconds, using the
  [same documented command](durable-task-acceptance-20261108.md).
- Focused authority checks: **PASS, 65 tests**.
- Wheel/source distribution build and archive inspection: **PASS, 10 fresh
  archives** across all five packages; no installation or runtime qualification.
- Critical changed-Python lint and whitespace: **PASS**.
- Final owned HTTP/process aggregate: **PASS, 34 tests, 3 deselected**,
  456.72 seconds, against the final external UI build. Exclusions remain only
  the two browser cases and the AF_UNIX attached-client case.

The independent review accepted the final live-cancellation guard, scope-alias
compatibility and stream changes with no remaining material finding in this
increment. It checked the final focused result and whitespace, not a separate
rerun of all aggregate suites.

Overall product acceptance remains **PARTIAL**. Real browser/phone/native-client,
configured provider, media/voice, connector and full runtime qualification remain
outstanding. The existing browser and AF_UNIX environment restrictions were not
bypassed. Publication/CI is blocked by the previously recorded GitHub integration
403. Runtime-local work remains preserved and requires separate reconciliation
before any separately approved deployment. These repairs do not create a new
authority model, grant access, replay uncertain external effects or implement
self-evolution.

## Broader-suite limits observed

An initial mistyped `--production` invocation was rejected by pytest; it is not
a passed production-path run. The wrapper then ran its default standalone
package suites, exposing the limits of this deliberately headless environment.
The correct `--production-path` invocation was subsequently run and passed as
reported above. The rejected/default-run log is retained as `production-third.log`.

The agent package had 1,110 passing tests, two skips and four failures from
missing `onnxruntime` / `llama_cpp` dependencies. The OS package had 542 passes,
23 failures and 14 errors around forbidden IPC sockets and the unavailable
default runtime directory. Media package collection also failed because that
headless setup lacks their import paths/dependencies. No all-package unit-suite
pass or complete media-capable environment is claimed. These limitations are
separate from successfully building and inspecting package archives. No socket
restriction was bypassed, privileged runtime directory created or missing model
runtime installed.

Aggregate logs under `/tmp/jaeger-baseline-20261108/`: `verify-third.log`,
`production-path-third.log`, `security-third.log`, `durable-third.log`,
`http-third.log`, `ui-third-build.log`, `packages-third.log`, `artifacts-third.log`.
Both root distribution archives were independently checked for the exact final
UI fingerprint. The canonical remote master was rechecked read-only and remains
`ff71bb769bc56e4c6d7be6d540a86be73e291e07`.

Final HTTP command, using the same disposable environment:

```sh
export JAEGER_WEBUI_UI_DIST=/tmp/jaeger-baseline-20261108/ui-third/dist
dev/scripts/run_tests.sh --integration -- --timeout=120 \
  --basetemp=/tmp/jaeger-baseline-20261108/http-third \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py \
  dev/tests/jaeger_ai/core/test_webui_document_journey.py \
  -k 'not owned_browser and not attached_client'
```

A follow-on audit reproduced a separate task-owner precedence defect: a fresh
partial artifact can override a yielded or blocked worker outcome and falsely
complete a durable task. That repair is being prepared separately from this
frozen increment. It is an additional reason not to treat these passing scoped
gates as complete product acceptance or deploy this candidate.
