# Concurrent commitment activation, 2026-11-08

## Defect and producer repair

The eleventh aggregate owned HTTP run exposed a real race, not just a slow
answer. A disk-low host initiative overlapped a scheduled request. Both unbound
TurnExecutives selected a newly created shared turn-loop commitment. After one
activated it, the other attempted the forbidden active-to-active transition and
failed before obtaining a native run or calling the model. The original failed
HTTP log and disposable state remain preserved; its polling deadline and answer
assertion were not weakened.

The existing commitment-store abstraction now provides atomic acquisition of an
active intention by kind. SQLite selects, optionally creates and activates in
one BEGIN IMMEDIATE transaction. In-memory acquisition/create/transition share
an RLock. Public transition remains strict. Each unbound request still creates
its own native run; sharing the existing per-instance intention does not share
execution ownership. Bound-run continuation is unchanged. Paused and terminal
commitments are not reopened. There is no schema change or exception swallowing.

This expands CommitmentStore's protocol. Both concrete repository adapters are
updated and independently checked. External custom adapters must implement
ensure_active_for_kind; there is no unsafe non-atomic compatibility fallback.
This narrow repair does not qualify all pre-existing general transition races.

## Evidence and limits

- Deterministic fail-before: three failed, three passed. Both adapters reproduce
  the stale created-state activation; concurrent first SQLite turns also expose
  duplicate intentions.
- Isolated candidate: 25 focused tests; 120 runtime/commitment tests passed.
- Merged main source: the same 120 runtime/commitment tests passed in 5.96 seconds.
- Independent review: 13 repository checks and 16 additional controls passed.
  Sixteen independent processes produced exactly one intention and 16 distinct
  native runs for both initially empty and already-created commitment cases.
  State selection, strict transition, protocol and transactional rollback were
  tested. Sandbox-blocked multiprocessing-manager sockets were not treated as
  a pass; independent processes with ordinary pipes supplied the verified proof.
- The unchanged cron HTTP contract passed in 7.67 seconds with the original
  15-second response deadline. Durable rows prove initiative and cron overlapped,
  completed separately and retained distinct native runs and assistant answers.
- Critical lint and whitespace checks passed. A first lint invocation could not
  create its default cache; the verified no-cache invocation writes no such state.

These counts overlap. This commit has focused producer qualification; full
combined application, HTTP and rebuilt-package checks are a subsequent gate.
A passing focused rerun does not erase the preceding eleventh aggregate failure.
No production state, provider account, credentials, browser or runtime Mac was
used. Actual browser/phone/native-host and installed-package acceptance remain
unverified. Whole-product and per-tab acceptance remain PARTIAL.

## Reproduction

Use the isolated environment from assistant-core-test-environment-20261108.txt,
with this checkout and its packages first on PYTHONPATH and all state/cache/temp
paths outside the source tree. Use a new basetemp each time; pytest removes an
existing one.

```sh
python -m pytest -q -p no:cacheprovider --timeout=60 \
  packages/jaeger-agent/tests/runtime \
  packages/jaeger-agent/tests/contract/test_commitment_store_contract.py \
  packages/jaeger-agent/tests/contract/test_sqlite_commitments.py \
  --basetemp=/path/to/new-isolated-test-directory
```

The owned HTTP fixture scripts only the provider boundary, restricts external
network access, and disables optional skill smoke subprocesses. It does not
qualify cold production skill initialization or non-core missing-smoke gates.
Exact commands, the failed chronology, independent controls, source hashes and
HTTP durable evidence accompany the review artifact. Rebuild both jaeger-agent
and root wheel/source archives after this change; stale agent archives must not
be carried forward merely because their version string is unchanged.
