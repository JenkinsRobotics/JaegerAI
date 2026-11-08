# Preserve admitted identity on retry, 2026-11-08

## Combined failure

The seventeenth combined HTTP run passed 49 cases, failed one, and excluded
three infrastructure-dependent cases. The existing
`test_new_chat_default_snapshot_survives_real_retry` found a producer regression:
an implicit unpinned first turn had no `_owner_agent`, as intended until routing
committed, but retry minted a marker from the now-current stable lead route.
The repeated execution no longer equaled the original immutable snapshot.

The original assertion and source failure are retained. No historical request
was rewritten and no test deadline or assertion was weakened.

## Repair

Admission now consults the canonical source before inheriting defaults. A
marker-bearing retry retains its existing current-identity mismatch rejection.
A markerless retry cannot gain a fresh marker from current routing. Internal
canonical-source continuations retain their existing source validation but do
not acquire new foreground qualification. A separate new request may use the
now-committed stable route normally.

This is a producer correction before request insertion, not a downstream
receipt fallback or permission expansion. The original request is unchanged.
Missing or foreign canonical source still fails through existing validation.

## Scoped evidence

Frozen candidate: 77a5ce715895cfb822833162dad6627cd8c18151, based on
35100a1e477a5eaebc21cd4fc66f3f25b530f015.
Patch SHA-256: 37e5e4570d51f94fd5bbd709e13647cf4cb136ef0c7e8a4b40958b3b55b80d04.
Only session_store.py and test_owner_request_journal.py change.

- Two producer controls fail before the fix: retry and canonical-source
  inheritance both incorrectly mint current lead proof.
- The unchanged real owned HTTP retry case passes: 1 passed, 43 deselected,
  8.44 seconds. This is targeted qualification, not the full HTTP result.
- Full journal/default/queue/TaskOwner scope: 268 passed, 67.19 seconds.
- Independent controls: baseline 3 failed/6 passed becomes 9 passed; 66 existing
  identity, route, retry and transfer controls pass separately. Counts overlap.
- Integrated production and test files match the reviewed candidate byte for
  byte. The [combined report](assistant-core-combined-qualification-20261108.md)
  records the later full integrated gates, including the separate artifact fix.

Evidence: jaeger-lead-retry-{before,after,http,regression}.log and
jaeger-retry-independent-{before,after,regression}.log in the cumulative bundle.

Overall/tab acceptance remains PARTIAL. This does not extend historical recovery,
change first-turn autorouting, qualify all specialist/background/attachment paths,
or imply real provider/browser/native-host acceptance. No runtime mutation,
remote write, merge or deployment occurred.
