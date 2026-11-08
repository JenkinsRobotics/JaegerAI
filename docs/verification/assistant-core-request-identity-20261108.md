# Request replay session ownership, 2026-11-08

Seventh isolated increment after `20ce255f41e519b70e1cd5bc046cf703c069bfe4`.
All preceding commits remain preserved. No runtime-Mac changes, default-branch
merge, deployment or further GitHub write attempts.

## Confirmed defect

The sixth increment protected task-owner receipt consumption against collisions.
A separate audit then found the underlying request store also accepted a global
request ID as replay identity without binding it to the destination session.

At the six-commit baseline, an isolated regression suite produced **four failures
and eight passing controls**. With the same request ID, text and choices, a turn
submitted to a different session returned the earlier completed output under the
destination session ID. A nonexistent destination was created and owner active
session state changed even though no new turn executed and the destination
transcript remained empty. Queued admission had the same replay defect. An
existing receipt also bypassed the supplied new-admission guard.

Version-two digest checks already rejected changed caller and tool choices.
Supported legacy version-one receipts use text-only digests, so a different caller
could reproduce the cross-session result through its own permitted session prefix
if it knew the request ID and original text. This was demonstrated using the real
handler, store and route-policy predicates, not live user data or production
bearer credentials. No new tool execution or tool-authorization escalation was
observed. Same-session replay and different-text conflicts were passing controls.

## Bounded repair

Both immediate and queued atomic admission reject an existing request whose
session differs from the destination, before creating or changing destination
state. The handler's global replay shortcut enforces the same binding before
model-validation bypass or owner-session activation. Generic identity conflicts
do not disclose the foreign session identifier, request details or saved output.

Request IDs remain globally unique. Existing same-session replay, digest checks,
legacy text-only compatibility within its authorized session, and terminal receipt
history remain intact. No schema migration or historical data rewrite is needed.

## Qualification

The first frozen patch passed 124 scoped tests, 85 independently rerun tests,
12 unchanged external regressions and an owned authenticated HTTP case. Subsequent
compatibility qualification found one failure among 62 existing foreground-transfer
controls: the stronger store now raised a request conflict during the admission
race, while the task owner expected to receive and hold a foreign receipt. The
owner now catches that specific admission conflict, checks for a newer attempt,
and retains the task paused without binding, dispatching or cancelling foreign
work. The strengthened existing race test checks unchanged foreign receipt,
paused state and safe repeat observation. Final compatibility coverage passed
167 tests; the independent transfer/recovery/race rerun passed 82.

Fail-before tests and exact observations are retained under
`/tmp/jaeger-baseline-20261108/request-identity-audit/`. Counts overlap; they are
not a unique-test total or whole-product acceptance.

The first aggregate attempt hit the isolated temporary filesystem's capacity
limit (`ENOSPC`), affecting pytest setup/output and package staging. Those logs
are retained as `*-seventh-enospc.log`, not counted as product passes. Closed
generated build/test archives were moved to the larger isolated workspace with
original-path symlinks; no source or evidence was discarded. Requalification
uses `/workspace/shared/jaeger-20261108-test-temp` for new temporary staging.

An ENOSPC temporary-directory fallback had left a generated pytest directory in
the checkout. The hygiene gate correctly rejected it. That directory was moved
intact to the isolated archive, not allowlisted; verification then passed.

### HTTP startup diagnostic and fixture boundary

The first completed post-storage HTTP aggregate reported **one failure, 36 passes
and three exclusions**. The failure preceded provider invocation at the existing
10-second provider-start assertion, before any cancellation request. Two
unchanged targeted main-checkout repeats failed there too. A clean six-commit
snapshot and the same snapshot with only the three new production-module changes
both passed, so the failure did not follow those changes in that controlled test.
Instrumented main-checkout runs passed; their timing changes do not exonerate or
explain the original failing runs.

Reliable sampled stacks showed five consecutive seconds in skill smoke-test
subprocesses during native initialization. The fixture had enabled optional smoke
checks, each permitting ten seconds, before an assertion requiring provider
entry within ten seconds total. This is a concrete uncontrolled setup dependency,
not proof of the exact blocking step in each failed run.

The synthetic owned HTTP profile now explicitly sets `run_smoke_tests=False`.
Production's default remains true and runtime code is unchanged. Real skill
loading, safety scans, native controller, tools, receipts, approvals and
cancellation remain exercised. The original provider-start deadline and all
cancellation assertions remain unchanged. The fixture does **not** now qualify
optional smoke subprocesses, non-core missing-smoke gating parity, or cold
production skill initialization. Existing smoke-enabled loader tests are retained;
those tests are not comprehensive production smoke qualification.

The unchanged cancellation test, identity HTTP case with fixture/default-setting
control, and existing skill-loader suite passed **16 tests**. The subsequent
full owned HTTP/process aggregate passed **37 tests, three deselected**, in
406.45 seconds. An independent final-byte rerun of the 16 focused tests passed
in 27.18 seconds; all eight frozen source/test hashes matched before and after.
Repository verification was rerun after the fixture change and passed again.
The exclusions remain exactly two browser cases and one AF_UNIX
client case. No earlier failure was erased or counted as a pass.

### Combined gates

Production source stayed frozen throughout the fixture investigation:
- Gateway session store: `1e4b2bb9681df06c8efb64e115befadfc66c94851edb5f627965d29f3987093d`.
- Gateway server: `3d8edb6d98b3d752382f4f31dbff956ee0da273bfc44f47caf5a05362247adfe`.
- Task owner: `b44e82809907cf30f6f962b2620798a1fc41f2c7589f15115b586bafe71c7fc7`.

- Repository verification: **PASS, 430**.
- Production-path: **PASS, 75**, 29.48 seconds.
- Security tier: **PASS, 203, two skipped**, 22.85 seconds.
- Expanded identity/durable/recovery aggregate: **PASS, 211**, 183.77 seconds.
- Focused identity/compatibility: **PASS, 167**; independent identity/auth:
  **PASS, 85**; independent transfer/recovery/races: **PASS, 82**.
- Final owned HTTP/process: **PASS, 37**, with the fixture boundary above.
- Unchanged UI component/build evidence: **PASS, 879 tests / 200 files** and
  the previously fingerprinted no-mock production assets.
- Root wheel and source archive: **PASS**; changed production modules byte-match
  source, no test temporary files were included, and the retained UI fingerprint
  matches. Eight unchanged companion archives were retained byte-for-byte; all
  ten pass archive inspection. No installation or runtime qualification.
- Critical lint, source-hash verification and whitespace: **PASS**.

Logs ending `-seventh-final.log` record aggregate results. Final HTTP source log:
`request-identity-audit/http-fixture-correction.log`; fixture-focused log:
`fixture-correction-focused.log`; final eight-file manifest:
`source-freeze-fixture.sha256`. Earlier startup failures, controlled comparisons
and stack diagnostics remain in the same audit directory. Exact expanded
aggregate commands are in the bundled `run-seventh-final.sh`, using the external
headless environment from the baseline. The final HTTP command uses the same
three test modules and exclusion expression, with a fresh shared temporary path.

## Remaining boundaries

Overall product and all visible destinations remain **PARTIAL**. This increment
does not qualify real providers, browser/phone/native-host journeys, external
accounts, or the configured runtime. Existing headless package and IPC limitations
remain. The six-commit foreground continuation support remains limited to its
versioned, fully specified subset. The separate default-admission candidate is
not included in this increment or counted as accepted.

No remote branch, PR or CI exists after the GitHub integration's write denial.
The deliverable is an isolated cumulative review patch, not a deployment.
Runtime-local work and user data remain untouched; reconciliation, backups, full
acceptance and separate cutover approval are still required.
