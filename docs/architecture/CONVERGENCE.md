> **Classification:** HISTORICAL.
> **Superseded by:** [`docs/CONTINUE_FROM_HERE.md`](../../docs/CONTINUE_FROM_HERE.md) (or `../../../docs/CONTINUE_FROM_HERE.md` from `dev/docs`).
> This is dated evidence. It may reference an old branch, HEAD, dirty worktree, or schedule. Do not treat it as current status, implementation order, or release qualification.

# Architectural convergence: implementation evidence

**Current release scope:** the [master plan](GROK_PERSONAL_RELEASE_PROMPT.md)'s
five-day RC contract supersedes historical ordering/freeze conditions below for
the scoped personal release. Full convergence is not complete. Preserve historical
evidence with its source identity; do not certify newer code from older counts.

## Product constraints

Preserve all features, all WebUI HTTP endpoints, and Gateway/Swift/Web behavior.
Keep Jaeger self-contained. Absorb Hermes capabilities before retiring donor
implementations. Keep all skills callable with scoped model visibility. Freeze
new features until runtime and state acceptance gates pass. Migrate legacy data
with verified backups before retiring old locations; do not delete operator data.

## Baseline tooling

`dev/scripts/architecture_inventory.py --summary` parses the tracked and
non-ignored untracked Python tree without importing application modules. Without
`--summary`, it emits a JSON file
inventory with imports, static tool decorators, route literals, environment
lookups, SQLite connection expressions, and execution entry points. Routes inside
named HTTP dispatchers include their statically inferred method and dispatcher;
prefix matchers are distinguished from mere string references. Symlinks are
recorded without recursively counting their targets. Runtime output belongs
outside the repository. `--emit-all-domains <external-directory>` writes the
source-derived feature, process/client, store, tool/skill, and HTTP inventories.

The verified 2026-09-22 scan covers 19,314 tracked files, 3 non-ignored untracked
files, 8,843 parsed Python files, and 470 SKILL.md files including vendors, with
zero parse errors. The earlier 260-skill count described the JaegerAgent subtree,
not the whole checkout. Ignored caches, bytecode and runtime artifacts are not
traversed.

This is discovery evidence only. Methods outside recognized dispatchers,
computed registrations and routes, response schemas, authorization behavior,
shell processes, and Swift interactions still need runtime characterization.
Route literals must never be presented as a complete endpoint compatibility
fixture.

## Verification and failure classification

New inventory parser tests pass both independently and under repository hooks.
An existing focused contract run reports 10 passed and 3 failed:

* Port uniqueness: unrelated modules use generic DEFAULT_PORT and
  DEFAULT_WEBHOOK_PORT names. The failure identifies ambiguous naming; it does
  not establish that two processes bind the wrong port.
* Source ownership: raw substring checks include donor tests and intentional
  Minecraft plugin metadata. Separate actual host defaults from valid features
  before repairing these assertions.
* Private session ownership: matching `/api/sessions` alone in donor modules
  does not establish access to another application's private state. Trace the
  destination and runtime callers before classifying a product defect.

The previous full unit attempt was interrupted and included sandbox errors and
an inherited JAEGER_STATE_DIR override that defeated per-test JAEGER_HOME values.
Its failure count is not a clean product regression baseline.

The product test setup now gives WebUI collection a disposable workspace.
This addresses collection isolation, not production import purity.
The three previously failing WebUI collection modules now collect 33 cases;
those cases plus the two inventory tests pass (35 passed). They cover cron
titles, session/profile authorization, streaming access checks, cancellation
authorization, and Gateway upload paths. This is targeted unit evidence, not
live Gateway/Swift/Web acceptance. A later focused inventory/test-runner check
passes 12 tests. Live acceptance is excluded from ordinary/full offline runs;
its explicit tier now requires a non-repository, non-operator
`JAEGER_STATE_DIR`, and the suite derives inspected stores from that root.
`git diff --check` passes.

The documented smoke tier now passes 169 tests (4,698 deselected). The first
full dev-unit baseline, before marker repairs, completed with 4,584 passed, 174
failed, 21 errors, 1 skipped, and 87 deselected. Socket denial accounted for the
errors and a substantial group of failures; those real-socket and real-child
process modules are now classified as integration/subprocess rather than unit.
Subsequent fail-fast unit passes exposed and repaired a stale `_run_turn` test
double, a generic-name port assertion that conflated unrelated services, and
source-ownership substring assertions that treated independent `/api/sessions`
routes, Windows/macOS path examples, and Minecraft support as ownership defects.
The later baseline results below supersede that failing dev-unit run. M0 is
still incomplete: passing isolated tests does not establish client acceptance.

Skill discovery now separates the full callable catalog from the deliberately
scoped automatic prompt-routing catalog. All installed, platform-compatible,
non-disabled skills remain listable, searchable, and explicitly loadable;
catalog policy controls only automatic routing. Focused skill suites pass 35 and
24 tests respectively. No bundled skill was deleted or archived by this change.

## Verified continuation: 2026-09-22

| Check | Observed result | Limit of evidence |
| --- | --- | --- |
| Dev unit, seed 20260922 | 4,504 passed, 1 skipped, 404 deselected | Not live client acceptance |
| Dev unit, networking denied, corrected markers | 4,495 passed, 1 skipped, 414 deselected | Nine actual-listener tests moved to integration |
| Unit collection, network/home writes denied | 4,505 selected, 405 deselected | Collection proof, not production import purity |
| JaegerAgent package unit | 922 passed | Also passes with networking denied |
| JaegerOS package unit | 229 passed, 56 deselected | Also passes with networking denied; hardware/integration excluded |
| Security tier | 187 passed | Includes controlled listeners; not deployment audit |
| Production-path tier | 61 passed | Scripted model boundaries, not full stack |
| Gateway daemon integration | 33 passed | Temporary stores/listeners; model execution stubbed |
| Gateway store process-crash recovery | 1 passed | Actual owned child killed; not provider effect replay proof |
| Owned Gateway/WebUI contracts | 7 passed, 1 expected failure | Real runtime/agent/handlers; cancellation is the explicit failing gate |
| Provider routing regression | 56 passed | Networking denied; includes same-name cross-provider selection |
| WebUI adapter listener contracts | 9 passed, 3 deselected | Real loopback listeners, scripted bridge |
| Swift offline suite | 139 passed | 2 live dispatcher tests excluded; external build directory |
| New WebUI response probes | 13 passed | Denied network/home writes; deterministic health/auth-backend inputs |
| Acceptance preflight safety | 25 passed | Rejects production ports and protected/symlinked state roots |
| Runner state-isolation subprocess | 1 passed | Harmless pytest stub confirms pre-collection environment |

Counts overlap and reflect their collection-time revision; the last seven auth
response cases and production model-selection fixes were verified separately
after the full unit run collected. Production-path tests were rerun after the
Gateway/runtime model-selection fix (61 passed); the subsequent router edge-case
fix passed the focused provider suite. Full unit qualification of the latest
revision remains outstanding.
Do not sum these results as unique tests. Logs and JUnit reports are
under `/tmp/jaeger-convergence-*-20260922.*`; the continuation checkpoint is
outside the checkout.

Repairs preserve the published MCP tool name `capability_inventory_tool` and
restore the existing skill-audit `active_count` field alongside the new counts.
The port scan now checks annotated canonical constants too. Personal-path
checks inspect executable Python literals rather than treating comments,
docstrings, regex fragments and donor documentation as hardcoded host paths;
positive scanner regression cases retain detection of real embedded paths.

Gateway integration initially failed 9 tests. Its tests shared a resident
EntityRuntime singleton, targeted stale execution seams, and supplied outdated
HTTP/model mock signatures. Per-test state/configuration and resident cleanup
now isolate the existing implementation. The real HTTP-startup test exercises
the OWNER lane; legacy MCP probes remain explicitly legacy. No production
execution branch was removed to make these tests pass.

Offline runners now replace inherited state overrides before collection,
including standalone package tests. Acceptance also requires explicit isolated
loopback listener URLs; it no longer restarts operator launchd services or
deletes arbitrary upload paths received from HTTP responses. The old live
suite's restart fixture deliberately fails until that suite is migrated to
owned processes. It still assumes a particular cloud model and is not a portable gate.
Swift's existing live dispatcher tests also require an owned-process harness.
Neither live suite was run against the operator's services.

The new owned-process contract tests go further than mocked runtime probes:
HTTP → Gateway → resident EntityRuntime → actual JaegerAgent → scripted external
OpenAI adapter response → durable terminal event. They verify identity and
transcript continuity after process death, duplicate-request replay without a
second model call, SSE replay, real file-tool approval/denial with disk assertions,
and WebUI login/CSRF/session/turn/SSE proxy behavior across a combined restart.
Only test-owned processes are killed. The child refuses outgoing connections
except its own Gateway listener; no live model or operator daemon is contacted.
The WebUI fixture uses real handlers but not the production launcher's model
warmups, dependency installation, or service-management steps; browser JavaScript
and live Swift networking remain unverified. During WebUI imports, missing
`psutil` prevents two donor tool modules from loading in the current venv; that
dependency/capability gap remains recorded, not silently treated as parity.

## Outstanding milestone gates

### Newly characterized runtime contracts

Session model selection previously appeared accepted but the OWNER constructed
the default model client. The debugging workflow reproduced that mismatch at
the actual provider boundary. Gateway now forwards session model/provider
selection into the runtime's existing client router and records the selected
provider/model in terminal telemetry. A separate router correction honors an
explicit provider switch even when both providers use the same model name.
Tests verify next-turn continuity, other-session isolation, and unchanged saved
configuration. Combined Gateway regression: 39 passed; provider regression: 56
passed. Attachment metadata also survives restart; traversal outside the
workspace, including symlink escape, is rejected.

Cancellation is **not qualified**. The owned-process reproduction receives the
cancel request while the provider is in flight, releases the scripted provider,
and observes `failed` instead of `cancelled`. Source tracing shows the Gateway
routes native-bound cancellation through legacy MCP even for OWNER runs; the
subordinate agent's interrupt event is not wired to that request. The test marks
only this exact observed error as expected failure; unrelated errors still fail.
This is an explicit unsatisfied acceptance gate, not a passing cancellation
contract. Repair requires request-scoped interruption, approval-wait release,
and effect-aware durable terminal status; an in-flight external effect must not
be described as undone simply because cancellation was requested.

### Remaining work

1. Complete route/method/auth/status/schema fixtures and client acceptance
   coverage; classify the complete isolated test baseline. Baseline incomplete.
2. Preserve observed resolver semantics in tests, then introduce configuration
   injection and explicit startup. `operator_state_root()` still appends
   `.jaeger_ai` to JAEGER_HOME and can migrate/create directories on every
   call from its ~35 real callers (unchanged — see the 2026-09-22 continuation
   below for what did land). WebUI settings also write during import; that
   is untouched. Full StatePaths injection (F01/F02's larger scope) remains
   outstanding.
3. Converge runtime ownership with cancellation, restart, approval and effect
   parity. Require actual process recovery tests before claiming idempotency.
4. Normalize tool registration and scoped visibility while preserving names,
   grants and discoverability. Measure routing before changing defaults.
5. Absorb WebUI/Hermes implementations with endpoint and capability parity;
   preserve required third-party licenses and attribution when code moves.
6. Enforce dependency, persistence, import-purity and client compatibility gates
   in CI. Remove donor code only after all capability parity gates pass.

No production runtime migration or vendor deletion has been completed yet.

## Verified continuation: 2026-09-22 (B01–B03, narrow F02/F05 slices)

Implementation prompt used: `RELEASE_AGENT_PROMPT.md`. External checkpoint:
`/tmp/jaeger-convergence.ZELAZ1Ue/CHECKPOINT.md` (full evidence, logs, and
the next queued task packet). This section is the durable summary; the
`/tmp` checkpoint is scratch and may not survive a restart.

**B01** — Reproduced the audit's fresh-verification numbers exactly before
any edit: focused inventory/model/WebUI-contract tests 22 passed; owned
Gateway/WebUI process contracts 7 passed, 1 xfailed (cancellation, A01,
still unresolved). Recorded baseline commit, dirty-file list, unstaged/
staged diffs, untracked/modified file hashes, and tool versions externally.

**B02/B03 (partial — not the full M0.2 matrices)** — Traced two concrete
defects to their exact current implementation before changing them:

- `operator_state_root()`'s eager `USER_ROOT = operator_state_root()`
  module-level assignment (`instance.py`) had **zero** readers anywhere in
  `jaeger_ai/`, `packages/`, or `dev/` — confirmed by full-tree grep. It
  was dead code whose only effect was an unconditional `mkdir` (and
  possible legacy-state migration) at import time, violating "resolution
  is pure." Removed. This is a small, real, non-hypothetical slice of A02.
- `setup_wizard.py:514`'s hardcoded `"Jarvis"` onboarding default (A09) is
  reachable only when `_pick_character()`'s persona shim is falsy — with
  the shipped character library `_character_shim` always returns a real
  object or raises, so today it is unreachable via the interactive picker,
  but it is still the textual default a scanner or a future caller with a
  falsy persona would hit. Replaced with the neutral `"Jaeger"`, matching
  `EntityIdentity.create_default`'s own existing generic default
  (`jaeger_ai/core/entity/identity.py:71`) — reusing an existing policy,
  not inventing a new one. "Jarvis" as an installed, user-selectable
  character preset and as an example value across `dev/tests/` is
  untouched; per the prompt's instruction, no global text replacement was
  applied.

**F02 (narrow slice)** — Landed only the two fixes above plus de-globalizing
the pytest-fallback state directory from a fixed shared `/tmp/jaeger_test_state`
path (a concurrent-test-process collision hazard) to a `tempfile.mkdtemp()`
directory memoized per-process (stable across repeated calls in one process,
unique across processes). The import-purity regression test was proven to
FAIL against the pre-fix code (temporarily restored via `git show HEAD:...`,
diffed byte-identical after restoring the fix) before being accepted as a
real contract, not a tautology.

**F01 (round 2, same session)** — Implemented, additive, zero migration of
existing callers:

- `StatePaths` (`instance.py`): frozen dataclass, `.resolve()` is pure
  (no I/O), `.ensure()` is the one explicit side effect. Matches
  `operator_state_root()`'s path output exactly for both override
  branches (proven by test, not assumed).
- `ResolvedRuntimeConfig` (new `instance/resolved_config.py`): frozen
  wrapper of `StatePaths` + a `Config.model_copy(deep=True)` snapshot,
  captured once. Proven: mutating the original live `Config` object after
  `.capture()` does not change the snapshot (the supported-live-edit
  concern the spec calls out for `/voice` and similar TUI mutators).
  `schemas.RuntimeConfig` (A05's name collision) is carried through
  completely untouched — verified by asserting its exact type name and
  field values survive capture.

**F02 (round 2, same session) — a new, real A02 sub-finding, root-caused
and partially addressed**: `scripts/install.sh` documents
`JAEGER_HOME=/opt/jaeger curl ... | bash` as normal usage — there,
`JAEGER_HOME` means *checkout location*. If an operator persists that
export (reasonable: so `jaeger`/`run.sh` find the same install later) and
then runs the product, `operator_state_root()`'s `JAEGER_HOME` branch
computes `<JAEGER_HOME>/.jaeger_ai` — state nested **inside the
checkout**, which is exactly what `AGENTS.md` section 1 forbids by name.
Confirmed: `./jaeger` (the real single entrypoint) sets neither
`JAEGER_HOME` nor `JAEGER_STATE_DIR` itself, so it inherits whatever the
operator's shell carries; `run.sh` is safe on its own (pairs
`JAEGER_STATE_DIR="$JAEGER_HOME"`) but only when both env vars flow
through it together.

Added, tested, **not yet wired into any production path**: `is_source_checkout(path)`
(walks up canonicalized symlinks for a `.git` + `pyproject.toml` ancestor)
and `StatePaths.resolve(reject_source_checkouts=True)` (raises when the
resolved root is inside one). Deliberately opt-in / off by default —
turning this on inside `operator_state_root()` itself changes observable
behavior for real installs in a way this session could not fully exercise
end-to-end (a fresh clone + the curl installer + a persisted shell
profile), and the right fix (reject vs. rename the checkout-location
variable) has real product-facing tradeoffs for existing operators. Left
as an explicit next task with both options spelled out — see the external
checkpoint's task packet.

**A10 investigated, not changed**: `packages/jaeger-agent`'s
`DefaultWorkspace` defaulting to `<cwd>/.jaeger_agent` is confirmed to
have **zero** production callers anywhere in `jaeger_ai/` (full-tree grep)
— the product always binds an explicit `InstanceLayout`. This is a
deliberate, documented design for a genuinely standalone embedder of the
reusable package, not a live product defect. Added a static regression
test (`test_ci_hygiene.py`) guarding the zero-caller invariant instead of
changing the package's public default, which is a decision for whoever
owns backward compatibility with third-party embedders.

**Still explicitly open:**

- The rest of F02: `operator_state_root()`'s 84 real call sites are
  unmigrated; the checkout guard is not wired into production; the
  `run.sh`/`install.sh`/`scripts/install.sh` `JAEGER_HOME` dual-meaning is
  reproduced and documented but not resolved.
- F03 (store/workspace/credentials/policy injection), F04 (migration
  manifest/backup/activation), F05's broader identity/onboarding
  convergence beyond this session's narrow Jarvis-fallback fix — none
  started.
- The full M0.2 capability/store/process/env/endpoint/tool preservation
  matrices — not started; do not treat M0 as closed.
- A01 (cancellation) is untouched and remains the required, unqualified
  release blocker. R01–R03, T01–T03, C01–C03, A01 (autonomy), H01–H03,
  Q01–Q03 are all untouched.

Verification (final, this session): 161 tests passed across every file
touched (`test_instance_resolver.py`, `test_resolved_config.py` [new],
`test_sensitivity_gate.py`, `test_clean_machine_install.py`,
`test_ci_hygiene.py`, `test_hermes_profile_adapters.py`,
`test_hermes_native_launcher.py`, `test_setup_wizard.py`,
`test_setup_wizard_prompts.py`, `test_commissioning_coordinator.py`,
`test_architecture_inventory.py`, `test_session_model_selection.py`,
`test_convergence_http_contract.py`, `test_acceptance_safety.py`), 27
deselected, 0 failed. Original B01 baseline suites re-verified unchanged
after every round (22 passed focused; 7 passed/1 xfailed owned-process —
the cancellation xfail, A01, is the same one from before any edit in this
session). `git diff --check` and `bash -n dev/scripts/run_tests.sh` clean
throughout. Full logs and the exact next-task packet are in the external
checkpoint (`/tmp/jaeger-convergence.ZELAZ1Ue/CHECKPOINT.md` at the time
of writing — treat that path as ephemeral; this section is the durable
record).

## Verified continuation: 2026-09-22, rounds 3–4

Every item below has executable evidence; logs are in the external checkpoint.

| Task | Change | Evidence |
| --- | --- | --- |
| F02 | `operator_state_root()` refuses a `JAEGER_HOME` inside a source checkout (fail loud; `JAEGER_STATE_DIR` never second-guessed). `./jaeger`, `run.sh` and the WebUI launcher no longer fall back to `<repo>/.venv`; the WebUI launcher resolves state through `operator_state_root()` instead of ignoring `JAEGER_STATE_DIR`. | `test_instance_resolver.py`; full unit tier green |
| F03 (slice) | A turn's approval policy is scoped to the turn (`use_policy`), no longer `install_policy`'d process-wide, where threads outside the turn resolved to another request's approval provider. | `test_runtime_policy_isolation.py` (reproduced before the fix) |
| F04 | `core/instance/state_migration.py`: phased, manifested, locked migration with a verified backup (SQLite backup API, WAL included), staging on the destination filesystem, integrity/row-count/hash verification, atomic activation, and resume. `legacy_state.py` uses it, fails closed, and no longer creates a compatibility symlink. | `test_state_migration.py` (21 cases incl. crash at 7 phases) |
| F05 | Retired unimported `core/instance/identity.py`/`persona.py` (hardcoded persona and a named person's profile); `mind/cognition` fallback name is the neutral default. | core/personality suites |
| R01 | Admission freezes model/provider/attachments/workspace/options (store schema v6, fingerprint v2; v1 receipts replay unchanged); execution reads only the snapshot; replay never re-points the session. | `test_gateway_admission_snapshot.py` (16) |
| R03 | Request-scoped cancellation (`core/runtime/cancellation.py`): registered at admission, bound to the agent, survives the loop's per-turn reset, interrupts the provider wait, wakes and denies pending approvals, 409 for late approvals, effect-ledger terminal truth, durable run closed. The owned-process **xfail is gone**. | owned-process suite 10 passed (in-flight interrupt without provider release, single terminal event, restart, approval-wait cancel, concurrent session); `test_request_cancellation.py` |
| T01 (slice) | One owner per tool name: a different handler under a taken name raises `ToolConflict` unless `replace=True` is declared. Measured first: 125 built-in tools, 0 conflicting re-registrations. | jaeger-os `test_tool_registry_ownership.py` |
| Q01 | CI calls `dev/scripts/run_tests.sh` (unit, Gateway integration, `--package agent/os/kokoro/whisper`), fails on in-tree junk, builds Swift and dists outside the checkout; runner never uses an in-repo venv. Layering ratchet (`test_package_layering.py`) and fresh-process import purity (`test_import_purity.py`). | `test_ci_hygiene.py`; mutation-checked gates |

**Privacy/import-purity defect removed**: `packages/jaeger-agent/jaeger_agent/tools/safari.py`
(swept into the shipped package by the "add previously untracked" commit)
read the operator's Safari bookmarks, printed them and wrote an index file at
import time. Deleted; the import-purity gate reports offending module names
and byte counts only, never content.

**Still open** (ordered by the queue): B02 full preservation matrices; F02's
84 call sites still resolve state per call (migration is now safe but still
invoked from resolution); R02 coordinator consolidation; T01 catalog injection
(the registry is still process-global), T02, T03; C01–C03 client acceptance
(Swift live networking, browser JS); A01 autonomy convergence; H01 (53
package→product imports, 19 core/mind→WebUI imports; `mind/cognition` is
unwired and needs a revive-or-retire decision), H02, H03 (WebUI launcher
still prepends a sibling hermes-agent checkout when present); Q02 clean
artifact install; Q03 runbook. No GitHub Actions run was observed.

### Round 4 additions (same day)

- **T03 slice**: every non-read tool call (local write, hardware,
  unclassified) now leaves a per-invocation intent/outcome record in the
  effect ledger; process death inside the call leaves it pending so the run
  reports *unknown*. Deliberate repeats are never deduplicated; external
  effects keep args-keyed crash-replay protection.
- **T01 slice follow-up**: the ownership invariant exposed two real
  duplicates in `jaeger_ai/main.py`: `help_me` (a wrapper that stripped the
  package tool's `side_effect="read"`; removed) and `reload_skills` (the
  product version honours the skill allowlist and audit hook but won only by
  import order; now a declared `replace=True` override).
- **Q02 artifacts**: all ten distributions build from a clean external copy,
  pass `inspect_release_artifacts.py`, ship their resources (260 skills) and
  none of the retired files; the non-editable wheels run from a fresh
  external venv with no checkout on the path and write nothing to HOME.
  A full PyPI dependency resolution on a clean machine is still unqualified.
- **Q03**: `docs/OPERATIONS.md` operator runbook.
- **H03 slice**: the WebUI launcher uses the vendored Hermes agent unless
  `JAEGER_HERMES_AGENT_SRC` names another checkout explicitly.
- **C01 finding**: the Gateway resident (`entity.resident.lock`) and
  `jaeger bridge`/TUI (`InstanceLock`) never check each other's lock, and the
  documented topology runs both, so one entity has two execution owners.
  Fixing it means making the bridge a translating client of the Gateway,
  which needs live Swift/TUI verification.
- Milestone tiers at the end of round 4: security 187, production-path 61,
  fault-injection 5, Swift offline 139 (0 failures), Gateway integration 44,
  full unit ~4,586 (0 failed), packages 933/290/10/6.
- Open observation: a `dev/__pycache__/bytecode_guard…pyc` reappears
  occasionally, most likely from editor pytest discovery running without
  `PYTHONDONTWRITEBYTECODE`; runner and CI runs do not produce it.

## Verified continuation: 2026-09-22, Round 5 (opt-in translating bridge)

Recorded in `/tmp/jaeger-convergence.ZELAZ1Ue/CHECKPOINT.md`. Gateway-backed
bridge execution is implemented and **opt-in**
(`JAEGER_BRIDGE_EXECUTION=gateway`); it is not the production default.

- Durable `turn.delta` / `turn.reasoning` streaming, `start_event_id`,
  Gateway-backed approvals and history, shared per-skill grants,
  `allowed_tools` snapshot/enforcement (`[]` stays no tools), dispatcher
  focus reports, attach-socket clients routed through the Gateway.
- Recorded evidence (those runs predated the last Round 5 edits; do not
  treat them as a qualification of this worktree's stopping point):
  unit ~4,587 passed; Gateway integration 51; bridge unit 115; owned
  contracts 19 then a separate attach test. This session did not rerun
  that full unit suite.

## Verified continuation: 2026-09-22, Round 6 (R02/C01 continuation + field parity)

External checkpoint: `/tmp/jaeger-convergence.nJEGqw/CHECKPOINT.md`.
`JAEGER_BRIDGE_EXECUTION=gateway` remains opt-in. Local execution is still
the default production path.

**Implemented (owner-side, not a per-client loop):**

- `run_continued_turn` in `jaeger_ai/core/runtime/autonomous_runner.py` is
  the canonical stall/ledger re-fire loop. Gateway `_continued_owner_react`
  uses it around one admitted request. Continuation prompts are inner steps,
  not new user messages. Loop-breaker / interrupt / cancel / kill-switch /
  step budget end the run. `EntityRuntime.run_subordinate_react` now returns
  `{"text", "halt_reason"}` so the owner can see inner-cap vs interrupt.
- Bridge Gateway mode forwards `display_text`, `is_subordinate`, and
  `attachment_ids` (empty lists stay empty). Admission snapshots those
  fields; `display_text` is what history stores, `input_text` stays the
  execution prompt; `is_subordinate` True skips the EntityRuntime
  salience wrap and runs owner ReAct, matching local `run_for_voice`.
  Retry with a different snapshot is 409; identical retry replays.

**Tested against this source (not a full-suite qualification):**

| Run | Result | Log |
| --- | --- | --- |
| Focused unit (continuation, admission, control-plane, policy isolation, bridge) | 157 passed | `r6-unit-focused2.log` |
| Owned-process Gateway/bridge contracts | 24 passed, 21 deselected | `r6-owned-process.log` |
| Cancellation + admission + native-runs + control-plane | 35 passed, 54 deselected | `r6-regression-gates.log` |
| Production-path tier | 61 passed | `r6-production-path.log` |

The 24 owned-process cases include the new stall re-fire, display_text
history, empty `attachment_ids`, and `is_subordinate` snapshot/replay
contracts, run together on this source. Full unit (~4,587), security,
Swift offline, and package suites were **not** rerun this round.

**Still open for R02/C01 (blocks making Gateway execution the default):**

- Bridge-hosted cron, heartbeat, idle supervisor, and webhooks do not
  start in Gateway mode; move producers into daemon composition without
  a second runtime.
- `create_runtime` / mind-node still constructs local execution.
- Swift `BridgeProcess` and live Swift/TUI transport (streaming, cancel,
  approvals, attachments, history, reconnect, restart, background).
- After those gates: make Gateway-backed execution the production path
  and retire the local execution owner. Preserve non-execution bridge
  commands (settings, onboarding, voice).

## Verified continuation: 2026-09-22, Round 7 (R02/C01 background producers)

External checkpoint: `/tmp/jaeger-convergence.nJEGqw/CHECKPOINT.md`.
`JAEGER_BRIDGE_EXECUTION=gateway` remains opt-in.

**Implemented**

- `jaeger_ai/core/runtime/background_producers.py` is the composition
  owner for cron, idle/heartbeat, and loopback webhooks. Producers submit
  through a `BackgroundTurnSink`; they do not construct an agent.
- Exclusive flock lease `<instance>/run/background_producers.lock`. The
  Gateway resident OWNER takes it at startup. A local-execution bridge
  takes it only when free. A Gateway-backed bridge never starts producers.
  Starting Gateway and a second starter together cannot double-run them.
- Background turns use stable request ids (`cron:<name>:<occurrence>`,
  `webhook:<delivery_id>`). Duplicate webhook delivery_id replays (409
  identity / replayed receipt) and does not call the model again.
  Disabled `webhooks.enabled` / `heartbeat.enabled` stay off.
- Gateway `_owner_tick` no longer fires heartbeat turns; sleep-time stays
  on the maintenance loop. Missed cron rows still claim via
  `claim_due_schedules` (one catch-up fire, then the next future slot).

**Tested against this source**

| Run | Result | Log |
| --- | --- | --- |
| Focused unit (producers, webhooks, background delivery, admission, continuation, bridge) | 181 passed | `r7-unit-focused3.log` |
| New owned-process producer contracts (4) | 4 passed | `r7-owned-c.log` |
| Full owned-process file | 28 passed | `r7-owned-all.log` |
| Cancellation + admission + control-plane | 35 passed | `r7-regression-gates.log` |
| Production-path tier | 61 passed | `r7-production-path.log` |

The 28 owned-process cases are the Round 6 set plus lease ownership, cron
fire, webhook replay, and gateway-mode bridge not taking the lease, run
together. A session-end live-tree fingerprint also reported concurrent
writes under the operator `~/.jaeger/instances/jaeger` tree (native-turns,
a ledger file) while those tests used isolated tmp roots; the 4-test
producer run did not trip that check.

Full unit, security, Swift offline, and package suites were not rerun.
Gateway execution is still not the production default.

**Still open for R02/C01**

- E. Swift `BridgeProcess` live transport against owned services.
- F. Default cutover after E.

## Verified continuation: 2026-09-23, Round 8 (R02/C01 create_runtime)

`create_runtime` (windowed `AgentCore` and `MindNode`) now prefers a
resident Jaeger Gateway, then a live bridge socket, and only then
`boot_for_tui`. `JAEGER_NO_ATTACH` skips both remote owners, so the suite
still reaches its local boot patch and does not probe the operator
Gateway. `allow_bridge_attach` pins `JAEGER_GATEWAY_URL` to a closed
loopback port so lifting the bridge gate cannot reach `:8810`.

Gateway execution mode for the bridge remains opt-in.

| Run | Result | Exit | Log |
| --- | --- | --- | --- |
| New mind-runtime unit | 2 passed | 0 | `r8-unit-mind-only.log` |
| Existing mind-node + attach isolation + attached runtime | 6 passed, 6 deselected | 0 | (same runner, no isolation failure) |
| Owned `test_create_runtime_submits_to_the_owned_gateway` | 1 passed | 0 | (integration) |
| Full owned-process file | 29 passed | 0 | `r8-owned-all.log` |

An earlier combined unit invocation reported operator
`hermes-webui-agent` config/profile mtime changes and exited 1 after 8
passes. The same files were not touched by the later isolated runs
(exit 0).

## Verified continuation: 2026-09-23, personal-release slice

Correctness fixes still present in the Round 7 producer path:

- Background `RequestConflict` returns `halt_reason=conflict` and empty
  text. It does not replay the previous output.
- A webhook `delivery_id` that creates a board card is remembered.
  The same delivery does not add a second card. Turn deliveries were
  already request-id stable.
- Producer `stop()` clears `_accepting` and joins cron/idle before it
  releases the flock. A stopped webhook server does not accept another
  delivery. A cron callback that loses the lease restores the claimed
  schedule instead of dropping it.
- A busy or failed cron admission restores `next_fire_at` so the
  occurrence can be claimed again.

Mac `BridgeProcess.launchEnvironment` sets
`JAEGER_BRIDGE_EXECUTION=gateway` unless the parent already set it.
That is the source default for the next app build. The installed
`/Applications/JaegerAI.app` was not rebuilt or restarted. An offline
Swift test proved the environment helper. It did not drive a live
Swift process through an owned Gateway.

| Run | Result | Exit |
| --- | --- | --- |
| Producer + admission unit | 31 passed | 0 (`r9` runner, this session) |
| `swift test --filter testLaunchEnvironmentUsesGatewayUnlessOverridden` scratch `/tmp/jaeger-swift-r9` | 1 passed | 0 `logs/r9-swift-launch-env.log` |

## UI exploration 2026-09-23 (scripted, Playwright)

Desktop-control tools and the in-app browser are not connected in this
session. Mac visual acceptance is `blocked_external`. WebUI was driven
with Playwright against an owned contract Gateway/WebUI
(`/tmp/jaeger-ui-owned`, ports from `listener.json`). The installed app
was not launched. Provider was the contract worker, not a live model.

Observed before the fix: the first chat returned HTTP 500 because
`Session.save()` opened `webui/sessions/<id>.tmp...` before that
directory existed. The page then queued messages 2–5 and listed the
first prompt twice. After `Session.save()` creates the parent directory,
five `POST /api/chat/start` calls in one session returned 200 and the
sidebar showed one WebUI session. Screenshots:
`/tmp/jaeger-ui-explore/shots/`.

The visible assistant text is still `AIAgent not available` (Hermes
import), not the Gateway's scripted `CONTRACT-ANSWER`. Profile chip
read `None`. That journey is `fail` for a real answer. Cancel, approval,
attachment, resize, reconnect, and the Mac app were `not_run` or
`blocked_external`.

Owned worker stopped (pid 20449). No operator database was opened.

## Operator scope decision — 2026-09-23: fresh-state personal release

The operator accepts starting with fresh conversations/memory; most historical
state is not worth mandatory migration. Preserve intended capabilities and new
memory durability, not every old transcript. Prioritize a working personal
assistant with real clients, voice/tools, background work, and feature UI wiring.
Full legacy upgrade coverage is deferred for this milestone; broader convergence
remains tracked separately. Existing working migration code need not be rewritten
or removed just to change the release scope.

The authoritative scope and archive rules are now in
`RELEASE_AGENT_PROMPT.md`, section 1. Before any future removal/reset, resolve
the exact state targets and preserve important or uncertain material in a verified,
dated Desktop archive (no plaintext credential exports), or leave its source
untouched. Start with a separate fresh instance; coordinate live cutover separately.

This documentation update did not copy, inspect, delete, or reset operator data,
restart services, or run application tests.

## UI exploration & acceptance — 2026-09-23 (Browser Subagent live verification)

A live end-to-end browser exploration run was conducted using `browser_subagent`
against an owned Gateway and WebUI instance (Gateway port 65063, WebUI port 65065,
isolated state root `/tmp/jaeger-ui-explore-run`). Provider was the deterministic
scripted worker in `dev/tests/fixtures/gateway_contract_worker.py`.

### Journeys Exercised & Verified

| Scenario | Result | Notes & Artifacts |
| :--- | :--- | :--- |
| **Authentication** | `pass` | Password login (`synthetic-contract-password`), redirection, CSRF token acquisition, onboarding dismissal |
| **Multi-turn Continuity (Turns 1 & 2)** | `pass` | Turn 1 and Turn 2 executed in the same session. History retained; zero message duplication, session resets, or server crashes |
| **Rich Markdown & Long Content (Turn 3)** | `pass` | Long response with Markdown headings, lists, Unicode emojis, and multiline syntax-highlighted code block. Smooth scrolling up/down verified |
| **Responsive Viewport Resize** | `pass` | Resized to 700x700 narrow viewport and restored to 1920x900. Navigation rail, composer, and message bubbles adapt cleanly without text overlap |
| **Slow Stream & Cancellation Recovery (Turns 4 & 5)** | `pass` | Slow stream processed; Turn 5 executed immediately afterward with zero residual busy state |
| **Session Isolation & Switching** | `pass` | Created Session 2, executed message, switched back to Session 1. Verified zero cross-session bleeding |
| **Panels & Navigation Audit** | `pass` | Navigated through Chat, Tasks, Kanban, Skills, and Settings. Workspace side-panel toggled open/closed cleanly |
| **Swift Test Suite** | `pass` | 142 passed, 2 skipped, 0 failures (`swift test --package-path jaeger_ai/interfaces/swift`) |
| **Core Smoke Suite** | `pass` | 169 passed in 18.14s (`./dev/scripts/run_tests.sh --smoke`) |

### Visual & Log Artifacts
- Video Recording: `webui_ui_exploration_1790150045757.webp`
- Narrow Viewport Screenshot: `narrow_viewport_layout_1790150544679.png`
- Final UI Exploration Screenshot: `webui_exploration_final_1790150951092.png`
- Owned worker cleanly stopped and ports freed. Zero writes to `~/.jaeger` or `/Applications/JaegerAI.app`.

## Five-day companion-assistant RC scope revision — 2026-09-23

Documentation-only planning pass on `next/clean-app`, `917e1eb8` plus dirty work.
Authoritative gates RC1–RC9, deferrals, schedule and next-agent prompt now live
at the top of `GROK_PERSONAL_RELEASE_PROMPT.md`. Target September 28, personal RC,
not public production certification. Status: **all final-candidate gates pending**.

Promoted into release scope: bounded physical voice, selected persona/memory,
existing face/orb presence and one useful contextual initiative. Held: broad IDE
worker automation, full 3D, full native feature-screen parity, mass restructuring
and complete Hermes absorption. No source capabilities or user state removed.

Read-only inspection confirmed current Web adapter and settings improvements,
existing IDE verification record, persona helpers, Gateway VoiceSession and Swift
orb/STT/TTS reuse opportunities. It also found two-second cancel-settle timeout
without a distinct pending outcome, malformed-attachment skip paths, unmeasured
usage defaults, native avatar mic setting without live capture, turn-based voice
and in-repo Swift build output. See CURRENT_PRODUCT_AUDIT.md for precise limits.

No application tests or graphical/live-provider checks ran in this pass. No
services restarted, installed apps replaced, paid calls made, operator data
accessed, commits/pushes made or protected source/staged edits changed. Historical
browser/Swift/process reports above remain reports of those runs, not this source's
release verdict. Next work: Day 1 launch/conversation qualification plus an early
physical voice latency probe; preserve one writer per shared boundary.

Documentation verification: automated relative-link/fence checks across all nine
updated documents and presence of RC1–RC9/hold-list/continuation-prompt passed
(exit 0). Scoped documentation `git diff --check` passed after whitespace cleanup.
A whole-worktree check also flagged a pre-existing extra EOF blank line in
`computer_use_v1/computer_use.py`; that unrelated source edit was left untouched.

## Swift freshness fix — 2026-09-23

Bounded assignment: replace wrong git-diff staleness check with a
content-fingerprint approach. Source committed to dirty worktree;
35 unit tests passed (13 new freshness cases). Bash execution blocked
for full candidate qualification run; exact status in
`CURRENT_PRODUCT_AUDIT.md` and
`/tmp/jaeger-overnight-review.Ix5Kny/CLAUDE_CANDIDATE_QUALIFICATION.md`.

| Check | Result | Limit |
|---|---|---|
| `--unit test_external_swift_build.py` (35) | pass, this session | Freshness logic only; no rebuild |
| App rebuild with `build-source-hash` stamp | **not run** — Bash blocked | Required before stale=False can be runtime-confirmed |
| `codesign --verify` re-check | **not run** — Bash blocked | Use prior-session result only until rebuild |
| Combined required unit/integration suites | **not run** — Bash blocked | Codex must rerun |
| Protected file hashes re-verified | **not run** — Bash blocked | VoiceStage.swift and roadmap untouched in this session |

RC gate status: all RC1–RC9 remain **pending final-candidate qualification**.
No new RC gate claims from this session.

## Overnight Claude delegation and independent audit — 2026-09-23

Operator authorized Claude work followed by Codex review. Actual signed-in Claude
Code was used, not a Codex subagent labelled Claude. Bounded assignments:
external Swift packaging/CLI discovery; then an independently reproduced IDE
attachment race after the existing IDE writer became idle. All delegated processes
from this handoff are now stopped/completed. No claim of unattended future work.

**Accepted source improvements, not a passed release:**

- IDE upload completions no longer stage into a newly selected conversation or
  resurrect a consumed attachment list. Review found a regression in the first
  guard (removing an older attachment discarded a different pending upload);
  explicit staged generation fixed it. Both independent reproductions passed.
- Swift build script and CLI callers now share `swift_build_dir`/`swift_app_bundle`
  in `cli/_common.py`. Default `~/.jaeger/apps/swift-build`; override
  `JAEGER_SWIFT_BUILD`. Reject in-repo/symlink/broad roots; no old `.build` fallback
  or new repo-root app symlink. `--print-build-dir` is read-only. CLI dev/lifecycle
  launchers pass `JAEGER_REPO` so external bundles have checkout context.
- Reviewer stopped a delegated revision after spotting tests that could write
  `~/.jaeger/test-shell-build` and invoke real Swift. That exact directory was
  absent on inspection. Replaced these with read-only resolution and a sentinel
  Swift executable in owned temporary state; enforced no-bytecode import in the
  producer. Did not delete old build directories or operator data.

Independent results on the final reviewed slices:

| Check | Result |
| --- | --- |
| IDE Node suite plus two external reviewer reproductions | 42 passed, 1 fixture-dependent skip, exit 0 |
| `--integration .../test_ide_gateway_client.py` | 1 passed, exit 0, 6.92 s; real owned Gateway, scripted provider |
| `--unit .../cli/test_external_swift_build.py .../cli/verbs/test_lifecycle_safety.py` | 31 passed, exit 0, 5.45 s |
| IDE stage-only packaging with pinned Markdown asset | pass; external staging, not VSIX installation |
| Shell syntax; new Python test Ruff; scoped tracked whitespace | pass |
| Protected VoiceStage.swift and staged roadmap SHA-256 | unchanged from before delegation |

Evidence/checkpoint: `/tmp/jaeger-overnight-review.Ix5Kny/AUDIT.md`, with exact
commands, failed-before logs, final logs, Claude reports and before-diff snapshot.
Historical broad-suite claims in Claude's first packaging report were not used
to certify this revision. Existing `_common.py` lint debt remains outside scope.

**Open review findings:** IDE model picker loses provider identity in the submitted
selection and its default label can disagree with the static extension setting;
settled activity can still render as "Using"; IDE attachments only register files
already inside the Gateway workspace. Preserve restrictions and implement actual
upload/selection contracts rather than hiding these gaps.

**Release gate:** still NOT QUALIFIED. Desktop-control calls timed out; final
Antigravity/Mac GUI, physical voice/latency, contextual outreach, cross-client
memory and off-LAN phone journeys remain unrun. No full `.app` build/activation,
operator-service restart, Jaeger paid-provider call, commit or push. Direct Finder
launch from arbitrary checkouts still needs a qualified backend discovery path.
Next: finish IDE provider/activity contracts, then actual external build and
owned-client/voice acceptance. Do not count these unit/process passes as RC1–RC9.

## Verified candidate qualification rerun — 2026-09-23 (Claude, executed)

Supersedes the "Bash blocked / not run" statuses above. Run on `next/clean-app`,
HEAD `917e1eb8`, dirty worktree; no source changes were needed. Scratch:
`/tmp/jaeger-overnight-review.Ix5Kny` (`v-*.log`).

| Step | Result |
|---|---|
| Scratch `build-app.sh` (`JAEGER_SWIFT_BUILD=<scratch>/swift-build`) | exit 0; bundle stamped `build-source-hash` (`1caba2152b6ae802…`) |
| `codesign --verify --deep --strict` on that bundle | exit 0 |
| `swift_app_is_stale(repo, bundle)` | `False` |
| Combined `--unit` (7 required files) | 95 passed, 1 deselected |
| Combined `--integration` (owned-process contract incl. browser + IDE client, no `-k` filter) | 32 passed, 152 s |
| `node --test jaeger_ai/interfaces/ide/tests/*.test.js` | 58 tests: 57 pass, 0 fail, 1 skipped (live-fixture case) |
| `swift test` (scratch path) | 162 executed, 3 skipped, 0 failures |
| Protected files (`VoiceStage.swift`, staged 0.9.3 roadmap) | SHA-256 unchanged from `before.sha256` |

Still unrun (unchanged): native GUI/installed-app launch, microphone/speaker
latency, live-provider inference, off-LAN phone, proactive-initiative journey.
The full RC remains unqualified; this qualifies only the packaged-scratch
freshness, unit, owned-process integration, IDE Node and Swift layers.

## Gateway-owned scope-app checkpoint — 2026-09-23 (Codex continuation)

The current release slice is now internally coherent for the local scope app:
the Gateway owns execution; the bridge is a Gateway client; the WebUI, IDE
surface, native MCP, and background producers connect through that owner.

**Root-cause repair made in this continuation:** the Gateway's `/health` check
probes the Chat Runner; the runner's health check attaches to the bridge.  The
Gateway-mode bridge was re-probing Gateway `/health` while serving every attach
handshake, creating a recursive health loop.  Each loop opened another Unix
socket and eventually stopped the bridge with `EMFILE` (too many open files).
The bridge now treats its successful startup admission as the warm readiness
signal for later attached clients, closes every per-client `makefile` stream,
and lets actual turn calls report a later Gateway loss.  The startup probe
remains fail-fast: it never falls back to a second local agent.

**Additional source fixes in this slice:** Gateway starts background producers
from the resolved instance layout even when EntityRuntime attachment is not
available; producer shutdown closes its webhook listener; isolated owned-process
tests use an ephemeral webhook port; a disabled-heartbeat test explicitly
disables webhooks rather than accidentally binding the production default port.

| Verification | Result |
| --- | --- |
| background producers + stack + bridge | 119 passed |
| bridge ownership + bridge protocol after loop repair | 112 passed |
| IDE orchestration Python unit tier | 32 passed, 4 deselected |
| IDE Node suite | 72 passed, 1 fixture-dependent skip |
| owned Gateway / IDE / WebUI-adapter concept suite | 52 passed |
| Live `jaeger stack status` | Gateway, bridge, Chat Runner, WebUI, native MCP, and Ollama all **Ready** |
| Live `GET :8810/health` | `status=ok`, `all_green=true`, bridge + native MCP agent ready |

This does **not** certify a full release.  No paid/live model turn, physical
Mac-app interaction, or installed IDE-panel conversation was performed in this
continuation.  Those are the remaining product-acceptance gates, not reasons
to weaken the owner boundary that is now working.
