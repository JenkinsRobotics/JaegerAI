# Assistant core baseline and release gate, 2026-11-08

## Current bounded terminal-recovery qualification

See [background-terminal-recovery-qualification-20261109.md](background-terminal-recovery-qualification-20261109.md) for original combined source 8027764, its mapped portable export
ace8382, bounded schema19/v4 terminal recovery and the separately attributed final
qualification ledger. The historical measurements below do not become later-source
passes. Overall and every tab remain **PARTIAL**. The new scope recovers exact
verified sealed output only. Delegated trees remain seal-ineligible; unsealed
interruptions are not automatically replayed. Canonical all-attempt graph vetoes
also prevent ordinary background-task completion or Stop from hiding unresolved effects.
Research consistency is not factual truth, citation entailment or authentic retrieval.
Fresh runtime-state comparison, local-data preservation and separate approval remain
required before release.


## Current background-admission qualification

See [assistant-core-background-admission-qualification-20261108.md](assistant-core-background-admission-qualification-20261108.md) for the exact ccda0c source/test freeze, all 18 selected final zero-exit groups, package provenance, new default/native authority, original-fingerprint replay, current-lease returned slices and terminal/workspace scope corrections. The measurements below remain historical and are not relabeled as new results. Overall and every tab remain **PARTIAL**. Background terminal journals and automatic interrupted Research replay remain absent. The data-preserving release/rollback proposal requires fresh runtime-state comparison and separate approval. Framework evolution remains deferred.


## Scope and revision

This is an isolated implementation pass, not a declaration that the entire app
is finished. Canonical remote: `https://github.com/JenkinsRobotics/JaegerAI.git`.
GitHub metadata and `git ls-remote --symref origin HEAD` independently identified
`master` at `ff71bb769bc56e4c6d7be6d540a86be73e291e07`. A fresh cloud clone was
clean before creating `fix/assistant-core-acceptance-20261108`.

The current task requires a dedicated branch/draft PR, no default-branch merge,
and no runtime deployment. Those instructions override the older direct-master
release workflow in AGENTS.md for this work. No runtime services, accounts,
credentials, chats or existing work were modified or imported into this clone.

Read AGENTS.md, PRODUCT.md, CONTRIBUTING.md, architecture and test architecture
before implementation. Repository-local `.agents` contains rules but no skill
packages. The canonical source and installed package ownership were inspected
rather than inferred from an old checkout.

## Live reference: read-only findings

The developer checkout, runtime source, installed wheel and served UI differ.
The runtime source was at `434fd01ee56ae72b347eb678f0c69bd5f7c4b90e` with 22
modified tracked files and six untracked files. Those changes include phone UI
and message actions. They are **not included automatically in this branch**.
No reset, stash, merge, removal, rebuild or restart was performed there.

Gateway, WebUI, bridge and MCP import runtime source ahead of installed wheels.
The served UI comes from an external cached build, not the runtime checkout's
`ui/dist`. Its build fingerprint matched the dirty UI source at inspection.
The installed wheel and in-tree UI build were different. A commit label or a
healthy transport probe is therefore insufficient deployment evidence.

Private host/user paths and runtime payloads are intentionally excluded from
this public repository report. The read-only inventory is enough to establish
that a later release must preserve and reconcile local work before cutover.

## Baseline before repairs

All state, Python environments, logs and test caches use disposable external
locations. No production API keys are present. The repository runner strips
credential-shaped environment variables, and owned-process fixtures reject
outbound connections except their own loopback Gateway.

- `scripts/verify.sh`: PASS, 430 tests across hygiene, IDE, frontend packaging,
  Gateway durability, interaction tiers, skills and wire contracts.
- UI `npm run build`: PASS, theme checks, TypeScript, Vite production assets and
  no-mock guard. Existing large-chunk warning remains.
- UI full Vitest baseline: PASS, 193 files / 807 tests.
- `dev/scripts/run_tests.sh --production-path -- -n 2 --timeout=90`: PASS,
  75 tests. This tier includes scripted model boundaries, not live providers.
- `dev/scripts/run_tests.sh --security -- -n 2 --timeout=60`: PASS,
  196 tests, two platform-dependent skips. Skips are not passes.
- Knowledge-library suite: PASS, 18 tests covering revisions, search,
  unknown write outcomes, concurrent edits and permission boundaries.

Initial owned-process integration: 31 passed / six failed. Four failures were
unconfigured build/browser prerequisites. UNIX-socket attachment was denied by
the cloud sandbox (EPERM). A cron time budget failure passed in a focused rerun.
These results are retained rather than silently replaced by later successes.

## Implemented repairs and supporting evidence

- Durable task admission checks cancellation/authority/attempt atomically.
  Concurrent settlement cannot consume a failed attempt twice.
- Task Stop reaches qualified owned children, including earlier attempts, and
  remains nonterminal until cessation is confirmed. Stale reconcilers cannot
  reopen a terminal task. Unknown effects are retained without blind retry.
- Existing task payload/history now records completion criteria, last observed
  progress, next action and blocker at request boundaries.
- WebUI SSE forwards Last-Event-ID on reconnect, using only WebUI's own upstream
  identity. It relays available bytes without flushing each individual byte.
  Cursor regressions failed before repair. A real local HTTP producer proves
  the first event reaches the client before the producer finishes.
- Production-shell settings, conversation and agent links, compact navigation,
  and workspace error states are repaired with component regressions. See the
  companion UI audit for the current navigation and backend inventory.
- A new owned HTTP journey creates/searches/reopens a real managed document,
  corrects specialist memory, rejects stale edits, rejects a read-only peer,
  restarts the Gateway and verifies exact stored content and idempotent receipts.

See [UI audit](assistant-core-ui-20261108.md) and
[durable task evidence](durable-task-acceptance-20261108.md).

## Browser and platform verification blocker

The official browser archive download returned an empty/invalid ZIP. Installed
`/usr/bin/chromium` was then tried in this isolated environment. It exits before
creating a page because `process_singleton_posix.cc` cannot create its UNIX
socket (EPERM). One scoped approved escalation produced the same result.
Further retries stopped. No screenshot, phone-width layout, browser back/forward
or physical iPhone/Mac outcome is claimed from component tests.

The independent AF_UNIX attached-client test encounters the same sandbox
restriction even under scoped escalation. HTTP, SQLite, worker subprocesses
and TCP streaming work. A separate isolated development host permitting browser
and local UNIX sockets is needed for those acceptance gates. Do not change
runtime Mac security settings or run these tests on production to bypass it.

## Data-preserving deployment and rollback proposal (not executed)

1. Obtain separate approval for the exact candidate revision and maintenance
   window. Review any active work, queued items and outstanding approvals before
   deciding whether interruption is safe. Do not auto-approve pending work.
2. Preserve the dirty runtime checkout, untracked files, served assets, installed
   package manifest and launch configuration. Use a verified filesystem snapshot
   or complete archive with a manifest; do not stash/drop/reset uncommitted work.
   Reconcile the phone/message changes into a reviewable candidate separately.
3. Back up each state store using its supported consistent snapshot/SQLite
   backup mechanism. Do not copy only a hot SQLite main file while ignoring WAL.
   Include knowledge and attachment stores and verify restore into disposable
   state. Keep secrets on the operator machine; do not put them in git or logs.
4. Build/test an immutable release outside the runtime directory. Run the missing
   browser/device acceptance and this suite against disposable data. Compare
   source, installed package and served UI fingerprints. Stage rather than edit
   code underneath live processes.
5. Only after approval and safe quiescence, switch the selected release and UI
   atomically using a reviewed cutover procedure, preserving the original tree
   and assets. Verify identity, chats, knowledge, approval states, queue counts,
   worker ownership, and source/package/served fingerprints. Perform one scoped
   user-approved live acceptance journey; transport health alone is insufficient.
6. If a release gate fails, stop only the newly started owned services and restore
   the previous source/package/UI release. Restore database snapshots only when
   schema compatibility demands it, preserving any post-cutover writes first.
   Never replay unknown external effects. Verify the same state/ownership gates
   after rollback and retain both release records for investigation.

The current deploy script rejects a dirty runtime, then uses `git reset --hard`,
rebuilds on the runtime host and restarts services. It is **not an approved command
for this task** and should not be invoked against the observed dirty runtime.
No merge, installation, cutover, data restoration or production restart was done.

## Evolution gate

GEPA and code-evolution frameworks are deferred until the core acceptance gaps
are closed. No framework was installed, no evaluator or authority rule was
relaxed, and the live assistant did not rewrite itself. Any future experiment
must use fixed independent/held-out tests, bounded budgets and separate promotion,
merge and deployment decisions.

## Final verification

The code under review is the local candidate based on the canonical revision above.
Record the exact checkout with `git rev-parse HEAD`; do not substitute the live
runtime's commit label. The final tested source fingerprint is
`b30f963e51fd2695dc2dafab1c02bb547b23d9738910d3363c81c929713736b2`, with
`mock=false`. The external build's index SHA-256 is
`46df121e73168f6c2d4ce215143c646e2a513bfa26acead21b5793b55b012573`.
The fingerprint independently matched the current source after the build.

| Final gate | Result | Scope |
| --- | --- | --- |
| Production UI build | PASS | Theme, TypeScript, Vite, no-mock guard; large chunk warning remains |
| Frontend components | PASS: 195 files / 833 tests | jsdom/components; not browser visual acceptance |
| `scripts/verify.sh` | PASS: 430 tests | Repository aggregate, same scopes as baseline |
| Durable owner/recovery aggregate | PASS: 81 tests | Atomic admission, cancellation tree, unknown outcomes, killed subprocesses |
| Production-path tier | PASS: 75 tests | Real stores/owner contracts; scripted provider boundary |
| Security tier | PASS: 196; 2 skipped | Existing negative permission/auth/trust-domain tests; skips not credited |
| Knowledge-library suite | PASS: 18 tests | Search, revision conflict, ownership, concurrent writes |
| New document/memory HTTP journey | PASS: 1 | Real document search/reopen, corrected notes and receipts after restart |
| Selected owned-process acceptance | PASS: 9 | Streaming, stop, approval/denial, WebUI auth/CSRF/proxy, five turns, durable verified artifact, memory and skill retrieval across restart |
| SSE + immutable build provenance regressions | PASS: 4 | Two cursor cases failed before fix; snapshot fingerprint case failed before fix; real HTTP incremental flush |
| Wheel/sdist build | PASS: 10 archives | Root and four packages; no install performed |
| Release archive safety inspection | PASS: 10 archives | Archive contents, explicitly not runtime qualification |
| Critical Python lint / diff whitespace | PASS | Changed Python files, `git diff --check` |
| Browser / phone layout / AF_UNIX client | BLOCKED | Sandbox EPERM, repeated once with scoped escalation; no page rendered |
| Native macOS shell / actual voice or media providers | UNVERIFIED | Not run in this Linux environment; no production credentials used |

The nine final HTTP/process checks reran the previously unconfigured WebUI cases
against the final external production build. The five-turn composer test verifies
streaming, cancellation, post-cancel reuse and persisted history. The skill test
now restarts Gateway and loads a saved recipe in a fresh Python interpreter.
The separate document/memory journey checks exact durable content and idempotent
receipts. These are complementary checks, not one single uninterrupted browser
journey, and test totals overlap across suites.

The external build helper had another provenance defect: it hashed the mutable
developer tree after compiling a copied snapshot. It now hashes the actual
snapshot, including shared reducer files. A concurrent-edit regression fails on
the old helper and passes after repair. This prevents a newer unbuilt edit from
being labelled as the served build.

### Reproduction

Use Python 3.12 and Node with the committed UI lockfile. The saved
`assistant-core-test-environment-20261108.txt` records the exact **headless test**
dependencies used, not a claim of a complete audio/model-enabled installation.
Create an external venv, set `JAEGER_VENV` and put its bin directory on PATH.
Keep HOME/state/cache under a disposable external directory. The repository test
runner isolates state and strips provider credentials. Do not use runtime state.

```sh
./scripts/verify.sh
dev/scripts/run_tests.sh --production-path -- -n 2 --timeout=90
dev/scripts/run_tests.sh --security -- -n 2 --timeout=60
python -m pytest dev/tests/jaeger_ai/features/knowledge_library -q -n 2 --timeout=60
python -m pytest dev/tests/jaeger_ai/interfaces/test_webui_sse_transport.py \
  dev/tests/jaeger_ai/features/webui/test_external_build_snapshot.py -q
# Full UI suite from jaeger_ai/interfaces/ui:
npm ci
npm test -- --maxWorkers=2
# Back at repository root; output-root must be outside the repository:
python jaeger_ai/interfaces/ui/scripts/build-external.py --output-root /tmp/jaeger-qualified-ui
export JAEGER_WEBUI_UI_DIST=/tmp/jaeger-qualified-ui/dist
dev/scripts/run_tests.sh --integration -- --timeout=120 \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py \
  -k 'owned_webui_auth or owned_webui_composer or durable_task_uses or memory_remember or skill_discover or owner_turn_streams or owner_cancellation_interrupts or real_tool_write'
dev/scripts/run_tests.sh --integration -- --timeout=90 \
  dev/tests/jaeger_ai/core/test_assistant_knowledge_journey.py
python scripts/install-packages.py --no-install --no-build-isolation --sdist \
  --ui-dist "$JAEGER_WEBUI_UI_DIST" --wheel-dir /tmp/jaeger-qualified-dist \
  packages/jaeger-os packages/jaeger-agent packages/jaeger-kokoro-tts \
  packages/jaeger-whisper-stt .
python dev/scripts/inspect_release_artifacts.py /tmp/jaeger-qualified-dist
```

Durable regression commands are in the companion task report. Build archives and
logs remain in disposable external storage; no runtime data is included in the
PR. Overall product acceptance remains **PARTIAL**, regardless of these totals.
Outstanding gates are real browser/device operation, configured-provider behavior,
external connector/media/voice workflows, and reconciling the preserved runtime
local changes before any separately approved deployment.
