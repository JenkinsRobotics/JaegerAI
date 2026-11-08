# Assistant-core reliability follow-up, 2026-11-08

This is the second isolated implementation increment, following local commit
`291676589a7aa7885bc7d55ca1f499c8a0a39f64`. Canonical master remains
`ff71bb769bc56e4c6d7be6d540a86be73e291e07`, verified again after the repairs.
The dedicated branch is `fix/assistant-core-acceptance-20261108`.
No default-branch merge, production deployment or runtime-Mac modification.
Preserved runtime-local work is still not automatically included in this branch.

## What changed

- Historic conversation rows now navigate to the exact selected session rather
  than the agent home. Source failures remain visible and retryable. Production
  shell route changes do not validate the old conversation against a new link.
- Knowledge skills, memory and Library reads reject stale context results and
  mismatched identities. The memory editor isolates agent/backend lifetimes;
  retired responses cannot rewrite a newer context's draft or pending intent.
- WebUI Markdown documents retain drafts through workspace navigation and reload
  in the same browser tab. Each tab has separate storage. Quota failures retain
  a page-session fallback; malformed recovery bytes are not overwritten. Missing
  server documents have explicit draft recovery rather than automatic recreation.
- Saves/deletes preserve uncertain outcomes and the original revision, including
  edit/revert races while a save is pending. Validated responses alone can claim
  Saved. AI edits cannot replace text or documents that changed underneath them.
  API failures have retry controls, and deletion carries the reviewed revision.
- The document backend serializes read/CAS/write/delete using existing atomic
  file primitives. Revisions advance with frozen/backwards clocks. Concurrent
  cooperating writers have one winner; stale/invalid writes cannot clobber it.
- WebUI `/v1/` authentication/profile failures return JSON401/403 rather than
  page responses. Authentication was already enforced: the initial HTTP-test
  failure was a login redirect followed to HTML200, **not an auth bypass**.

The existing document store, API names and app structure remain. No new task
scheduler, credentials, external account action, provider installation or
self-evolution framework was introduced.

## Evidence and limits

Detailed scoped commands, initial failures, final focused results and limitations:

- [Historic conversations](historic-session-navigation-20261108.md).
- [Knowledge request ownership](knowledge-request-ownership-20261108.md).
- [Document draft recovery](document-draft-recovery-20261108.md).
- [Document persistence and owned HTTP journey](document-persistence-20261108.md).

Twenty-four backend regression cases fail against the preceding implementation
and pass after repair; they cover several families of concurrency, revision and
delete failures, not 24 distinct product defects. Six of the initial seven draft
UI regressions failed before repair. Independent review found additional recovery
loss and retired-response races; they were repaired and covered before final
aggregate verification.

The expanded existing owned Gateway HTTP/process suite passed **33 tests**, with
exactly the two browser cases and the AF_UNIX attached-client case deselected.
It covers streaming, cancellation isolation, approval/denial and grant reuse,
attachment boundaries, bridge routing, scheduled work, producer ownership,
durable artifacts, memory and skill retrieval across restart. Scripted model
boundaries and synthetic local effects remain, not real-provider qualification.
The new WebUI document HTTP journey passed **one test** against real owned servers:
auth/CSRF rejection, create/read/save, stale PUT/DELETE409, exact payload after
both-server restart, and revision-bound deletion. Auth/CSRF/profile checks:
**37 passed**. Backend document checks: **36 passed**.

Browser/device acceptance remains blocked by executor UNIX-socket restrictions;
no new browser or runtime-host workaround was attempted. UI component tests do
not prove actual phone layout, native app operation or configured provider/media
behavior. Per-tab overall acceptance remains PARTIAL.

Draft durability is intentionally limited: tab storage survives reload in that
tab, not permanent tab closure. Before-close prompts are best effort. A memory
fallback cannot survive process death. Only an explicit server save is permanent.
The old document API has no operation-ID receipt for POST creation; a lost reply
is reported as uncertain and refreshes the list without automatic replay. A user
can still intentionally create another document. Unknown writes are not silently
rebased or retried. File-lock guarantees require cooperating writers sharing the
same canonical lock directory; see the backend report for filesystem limits.

## Integrated verification

Final build, aggregate counts and source fingerprint follow. Test totals overlap
and must not be summed as a unique-test count.

Final tested production-source fingerprint:
`0ed2b334ae2fbf04bf8875be0502e7bdd921eedd1c2094756eddb3e2bb7282b8`.
Independently recomputed from current source and matching `build.json`,
`mock=false`. Index SHA-256:
`81f32fa9bdd5d9aa78f620a37bd42901b3d78ecea6bbb894babdaf6705f449af`.
Build snapshot: `/tmp/jaeger-baseline-20261108/ui-second/build-xu64xhx0/ui`.

| Gate rerun on this increment | Result | Evidence boundary |
| --- | --- | --- |
| Full UI component suite | PASS: 199 files / 874 tests | jsdom; 147.35 seconds; warnings retained |
| External production UI build | PASS | Fresh locked dependency install, theme, TypeScript, Vite, no-mock; existing chunk-size warning |
| Repository `scripts/verify.sh` | PASS: 430 tests | Same documented hygiene, frontend, Gateway and wire tiers |
| Production-path tier | PASS: 75 | Scripted provider boundary |
| Security tier | PASS: 196; 2 skipped | Skips not counted as passes |
| Expanded owned HTTP/process suite | PASS: 33; 3 deselected | Known browser and UNIX-client infrastructure exclusions only |
| New document HTTP journey | PASS: 1 | Real authenticated WebUI CRUD and restart, synthetic content |
| Final-build HTTP smoke | PASS: 2; 35 deselected | Document journey and existing auth/proxy journey against final external assets |
| Document backend regressions | PASS: 36 | 24 new plus 12 existing; real threads/processes and direct API routes |
| Auth/CSRF/profile regressions | PASS: 37 | Includes eight new classification cases |
| Wheel and source distribution build | PASS: 10 archives | Five packages; no installation or runtime qualification |
| Archive safety inspection | PASS: 10 archives | Contents check, not deployed-runtime validation |
| Critical Python lint / whitespace | PASS | Changed Python E9/F63/F7/F82; external cache; diff check |
| Browser, phone and native-host acceptance | BLOCKED / UNVERIFIED | Unchanged limitations; no workaround attempted |

Reproduction uses the external Python environment and UI lockfile documented in
[the first increment](assistant-core-baseline-20261108.md). The documented tier
commands remain the same. For the expanded HTTP suite:

```sh
export JAEGER_WEBUI_UI_DIST=/tmp/jaeger-baseline-20261108/ui-second/dist
dev/scripts/run_tests.sh --integration -- --timeout=120 \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py \
  -k 'not owned_browser and not attached_client'
dev/scripts/run_tests.sh --integration -- --timeout=120 \
  dev/tests/jaeger_ai/core/test_webui_document_journey.py
```

Use disposable HOME/state and the external venv as in the baseline report.
Logs under `/tmp/jaeger-baseline-20261108/`: `ui-second-tests.log`,
`ui-second-tests/results.json`, `ui-second-build.log`, `verify-second.log`,
`security-second.log`, `production-second.log`, `http-expanded.log`,
`second-build-http.log`, `packages-second.log`, `artifacts-second.log`.
Focused logs and commands are in each companion report. No in-source runtime or
cache directories were introduced. The independent review closure found no
remaining material issue in the reviewed change scope; it did not independently
rerun these aggregate tests or qualify browser/runtime behavior.

Overall product acceptance remains **PARTIAL**. Real provider, media/voice,
connector and browser/native acceptance, publication/CI, runtime-local work
reconciliation and a separately approved deployment are still outstanding.
