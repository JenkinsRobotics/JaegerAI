# Reconciliation ownership and visible outcomes, 2026-11-08

Tenth isolated increment after `acf72257da36ae181a0514c7c8eae45954d905a6`.
All preceding commits remain intact. No runtime installation, rebuild, restart,
merge, deployment or retry of denied GitHub writes.

## Backend defects and producer repair

A reopened durable store correctly holds queued work behind an unknown request.
But confirmed reconciliation settled that request without draining the eligible
queue. Completed, failed and cancelled receipts all reproduced the stranded queue;
calling the existing drain manually immediately started the eligible successor
and preserved the paused item.

Adding a drain exposed another producer invariant: late settlement of old
acknowledged work unconditionally changed the session status, even while newer
work was admitted, running, awaiting approval, cancelling or unresolved. A direct
probe showed a third request could then be admitted alongside a newer active
request. An initial ownership guard protected active work but independent review
proved it still overwrote a newer terminal failure with idle.

The retained repair uses the latest durable `turn.start` admission event in
`activity_history`, matching request and turn identity inside `BEGIN IMMEDIATE`.
Both initial admission and queue promotion write that evidence transactionally;
creation time is not substituted for promotion order. Other live or unacknowledged
unknown owners remain protected. The old request's result and terminal event are
still recorded, but it cannot overwrite another owner's session status.

Confirmed, non-replayed terminal reconciliation now invokes existing queue drain.
It retains `turn.reconciled`, native-receipt provenance and current response shape;
it does not add the ordinary terminal path's notification or entity side effects.
Unknown/pending receipts, acknowledgement-only, explicit pauses, authorization
and Global Stop retain their existing boundaries. Disconnected observers do not
prevent settlement or queue progression.

Missing or mismatched historical admission proof conservatively preserves session
status. Such legacy sessions can remain blocked; this patch does not manufacture
ownership from mutable timestamps or rewrite old receipts.

## Client defects and partial-output repair

Actual store-generated failed/cancelled reconciliation events passed through the
SSE parser and real WebHost recovery as successful `complete` states. Mounted
MinimalChat suppressed the failure message. It did not display a literal
"Completed" badge, and no such visible wording is claimed here.

The event mapper now uses the existing durable request-outcome producer, retaining
completed, failed, cancelled and unknown distinctions. Missing or nonterminal
statuses cannot imply success. Identity, replay cursor and reconnect controls are
preserved; recovery does not submit the work again.

Independent review caught a second defect in the initial candidate: an empty
failed/cancelled receipt emitted a final empty text item and erased already
streamed partial output. The shared outcome producer now preserves that text for
non-success empty receipts, including request-status fallback. Nonempty final
output remains authoritative, and successful completed-empty semantics remain
unchanged. The tests exercise actual normalization, WebHost, followTurn, reducer
and mounted MinimalChat, not a mocked terminal result.

Cancellation and completion still have no explicit textual label in MinimalChat
when no tool row exists. Their distinct state is proven; no new status badge or
browser visual acceptance is claimed.

## Candidate evidence and review corrections

- Backend first expanded fail-before suite: 14 failed, 13 passed.
- Additional chronology fail-before suite: 11 failed, four passed.
- Backend final candidate: 123 passed, including 44 new regressions; hygiene nine.
- Independent backend v2: 90 passed, including 20 concurrency probes and the
  previously failing newer-terminal-history regression.
- Initial UI audit: four failed, nine passing controls, including real mounted
  suppression of failed reconciliation.
- Independent empty-receipt proof: four failing reducer/mounted cases with the
  completed control passing. This candidate was withdrawn before integration.
- Revised UI candidate: 71 passed with 31 new tests, TypeScript passed.
- Independent revised UI: 76 passed, including five extra reducer/mounted controls.

The reviewed backend and client patches applied cleanly after the ninth commit;
all corresponding source hashes matched. Final merged qualification:

- Production-path: **PASS, 75**, 26.89 seconds.
- Security: **PASS, 203**, two platform skips, 20.51 seconds.
- Durable/recovery: **PASS, 319**, 119.48 seconds.
- Repository verification: **PASS, 430**.
- Full UI: **PASS, 910 tests in 201 files**, 162.56 seconds.
- Theme literals, TypeScript, production build and no-mock guards: **PASS**.
- Owned HTTP/process aggregate: **PASS, 43**, 454.81 seconds; three existing
  browser/attached-client infrastructure exclusions remain.
- Root wheel/sdist rebuilt, eight unchanged companion archives retained; all ten
  archive checks pass. Six root and two agent runtime modules match exact source,
  and the root archives contain the verified new no-mock UI build.
- Changed Python critical lint and diff whitespace: **PASS**.

Independent post-test comparison matched all 866 snapshot source files against
main and the manifest's 857 hashed inputs. The source fingerprint is
`36612489016ec2283f86dcc22d435be6aa80478591ab9dcb4551833c7be0fc1f`, lock hash
`02c93b6498072395b20501296f0afd95b6fe8fe9807adc64da9f8929a8e7f128`, and built
index hash `943ff7a9e4e5451a318ba2a0d0a1808e07346e837199f14f711966187e5773a8`.
The entry `/assets/index-BieAlCh3.js` has SHA-256
`204e384d94105eab9fc6c0d8a3df2ce42265644d5e0c5fe6a1254699308bf651`.

The six-file main runtime/test manifest SHA-256 is `f0dc7ad58c2783e6962ff104f4f08d3e091bd3e250c9112edbc4e223f9e78662`.
All hashes were rechecked after qualification. Counts overlap. The external
build/test used existing matching dependencies and external caches; preexisting
checkout dependencies were preserved, not removed or claimed absent.

`run-tenth-final.sh` records exact Python gate/environment/target commands. The
UI evidence includes `COMMANDS.txt`, machine-readable test results, build logs
and independently verified input metadata. Use disposable external HOME/state,
Python 3.12 and the existing lockfile. No command targets runtime state.

## Evidence boundaries and remaining acceptance

The new backend reconciliation tests reopen the actual durable store, but supply
controlled native receipts and record dispatch in-process. They do not claim a
real native-bridge crash/receipt/restart journey. The existing owned HTTP worker
uses resident EntityRuntime; manufacturing a bridge receipt for that execution
would be wrong provenance. A genuine bridge test must interrupt owned transport
after its actual receipt persists, not invent a terminal outcome.

Owned HTTP tests elsewhere retain their scripted provider boundary and explicit
optional-skill-smoke exclusions. Production defaults are unchanged. Browser,
phone, native host, installed runtime and real providers/accounts remain
unqualified. Overall product and all tabs remain **PARTIAL**. Unsupported routes,
old receipts, attachment continuation, same-tab draft limits and unknown document
creation outcomes remain bounded as previously documented.

No runtime-local work or user data is overwritten. The review candidate is not a
remote PR or deployment. Reconciliation of existing runtime changes, backups,
complete acceptance and separate cutover permission remain necessary.

## Later conservative receipt routing

The next [resident receipt-routing increment](assistant-core-resident-receipt-routing-20261108.md)
rejects wrong-engine proof. Its focused checks pass, but the subsequent aggregate
HTTP run exposed a separate commitment-activation race and remains PARTIAL.
The successful HTTP result recorded here applies to this tenth increment only.
