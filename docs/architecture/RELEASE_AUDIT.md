# Release convergence audit — 2026-09-22, with continuation update

**Historical architecture audit.** Current five-day scope and acceptance are in
[the master personal-release plan](GROK_PERSONAL_RELEASE_PROMPT.md); newer source
findings are in [CURRENT_PRODUCT_AUDIT.md](CURRENT_PRODUCT_AUDIT.md). Do not treat
all items below as prerequisites for the scoped RC or their old status as current.

Implementation specification: [RELEASE_AGENT_PROMPT.md](RELEASE_AGENT_PROMPT.md).
This audit supersedes the old handoff's claim that only 35 targeted tests and two
inventory tests exist. It does not supersede newer code or evidence collected
after this snapshot.

## Current continuation update — Claude rounds 3–4 and UI coverage

The original findings and original test counts below are historical. Use section
3 of the revised implementation prompt for current task status. This update
incorporates the user's Claude report, the latest sections of
`/tmp/jaeger-convergence.ZELAZ1Ue/CHECKPOINT.md`, selected recorded test logs, and
direct inspection of the changed source/tests. No application tests were rerun
for this documentation update.

Implemented with recorded regression evidence: R01 request snapshots/digest
versioning and R03 cancellation/approval closure. The old cancellation xfail is
gone; the current owned-process tests prove interruption without releasing the
provider, single final outcome, restart continuity, late approval rejection and
isolation from a concurrent session. Keep these tests through owner migration.

Existing primitives now include StatePaths and ResolvedRuntimeConfig. A phased
`.jaeger_os` → `.jaeger_ai` migration and naming fixes are present. Request policy
is scoped; tool-name conflicts require explicit replacement; non-read effect
intent/outcome recording has expanded. CI uses the local runner; launcher venv
fallbacks and implicit sibling-Hermes discovery were repaired. A runbook and
external artifact build/install evidence exist. These are meaningful completed
slices and must not be recreated by the next agent.

Limits verified in the current source/checkpoint:

- `operator_state_root()` still initializes/migrates when resolving; pure
  primitives are not production-wide injection. `ResolvedRuntimeConfig.capture`
  isolates the original Config, but its exposed nested Config remains mutable.
- F04's verified directory migration does not close every legacy path, per-instance
  schema migration, conflict and rollback requirement in the complete plan.
- Generic persona fallbacks were fixed; the standalone DefaultWorkspace still
  uses `<cwd>/.jaeger_agent`.
- Q01's dependency ratchet permits existing baselined debt; its import test covers
  selected package roots/stdout/scratch-file changes, not all forbidden effects.
- Q02's non-editable test uses an external venv with existing third-party
  dependencies via a read-only path entry. Fully independent dependency resolution,
  all-client acceptance and the final vendor-free artifact remain unqualified.
- Gateway resident and bridge/TUI execution ownership remain separate. C01 needs
  a translating bridge and owned Swift/TUI/Gateway transport tests. This is already
  authorized implementation work; it does not require a live operator restart.
- Dormant `mind/cognition` needs intended-capability mapping. Preserve its intended
  behaviors through canonical services and retire duplicates only after parity;
  a missing static caller is not permission to delete desired functionality.
- CI Swift builds use external scratch, but the native build-app script still
  produces an in-repo app/build. Fix script, launch/discovery references and docs
  together without deleting/replacing the running operator app.

Privacy repair: the unregistered Safari import-time scraping script was removed.
Preserve that deletion and test. Do not restore it for file-count parity or expose
private bookmarks in test/audit logs. Legitimate browser tools remain separate.

Recorded latest results: 4,586 unit passed, 1 skipped, 424 deselected; Gateway
integration 44; agent package 933; OS 290; Kokoro 10; Whisper 6; security 187;
production-path 61; fault injection 5; Swift offline 139. These are Claude's
recorded runs, not a new full qualification. The actual GitHub CI run, live
Swift/browser interaction and hardware/provider checks remain distinct.

The feature-to-UI source review also found four reachable Swift prototypes:
SkillsView uses sampleCatalog, TasksView uses sampleTasks, KanbanView uses a sample
board, and WorkspaceView uses a sample snapshot and simulates commit success.
WebUI already has API-connected skill/memory/cron/workspace panels; finance has
an extension dashboard and Swift intents. The problem is incomplete/concurrent
ownership and unfinished wiring as well as missing controls, not an absence of
all UI. The revised prompt adds U01–U06, a 15-row feature-to-surface seed matrix,
truthful unavailable/demo states, preservation of existing interfaces, finance
policy/provenance reconciliation, real XP-event wiring and mandatory UI acceptance.

The original 24-row task queue now has 30 rows, including the six UI tasks.
The current prompt directs continuation from existing progress and the R02/C01
ownership gap rather than redoing the initial configuration/cancellation work.

## Conclusion and audit scope

Jaeger has working end-to-end behavior and substantial existing infrastructure.
The remaining assignment is architectural convergence plus release qualification.
A new blank repository, new language stack, or duplicate execution framework is
unnecessary. Physical modularization should accompany ownership/caller migration;
mass file moves would not fix global state or competing execution owners.

The original M0–M5 ordering is still useful. The replacement prompt adds source
anchors, small task packets, explicit lifecycle behavior, dependency order,
preservation matrices, and measurable gates. It lets a less capable agent work
on one bounded owner without deciding the overall architecture again.

Reviewed: repository instructions, current dirty worktree, prior handoff and
checkpoint, user-supplied Gemini transcript, architecture docs, root manifests,
CI/test runner, state resolver and launchers, Gateway admission/cancellation,
EntityRuntime, model routing tests, tool registry/schema/executors, package
workspace and memory bindings, ownership declarations, relevant cognition imports,
identity onboarding, client aliases, features and additional client trees.

This is a targeted architectural audit backed by a refreshed static scan and
focused executable checks. It is not a manual review of all 19,000 files, a
penetration test, a current full-suite release certification, or a live operator
session test. Runtime observations are distinguished from source-derived risks.
No application source or existing tests were changed during this audit.

Base commit: `917e1eb89b80dafc0524c9e4355a3bae5a56e644`.
Worktree is dirty, including staged roadmap work and user Swift changes. The
implementation prompt is written for that worktree, not the clean commit alone.

Fresh static inventory, before these two new documents:

| Item | Result |
| --- | --- |
| Tracked/indexed files | 19,315 |
| Nonignored untracked files seen by scanner | 10 |
| Python files parsed | 8,849 |
| SKILL.md files across product and donor trees | 470 |
| AST parse errors | 0 |
| Recognized limitations | Dynamic registration/routes; response/auth contracts; non-Python semantics |

These counts are not required future totals. Preserve capabilities and provenance,
not redundant file counts. Python emitted several invalid-escape SyntaxWarnings
while parsing; zero AST errors does not establish lint correctness.

## Findings ordered by consequence and dependency

### A01 — Cancellation cannot yet qualify for release

**Runtime reproduced; release blocker.** The owned-process cancellation case is
an expected failure. Gateway accepts cancellation while the model is running,
then records `failed` after the provider is released. Seven other process cases
pass.

Source: `jaeger_ai/core/gateway/server.py:1952` (`handle_cancel_turn`) and
`:1983` (`_request_native_cancel`), plus
`jaeger_ai/core/entity/runtime.py:704` (`run_subordinate_react`). OWNER requests
receive legacy MCP cancellation rather than a signal wired to their in-process
agent. The agent's existing event is cleared when `run_turn` starts, and
`jaeger_agent/cognition/executive.py` records interrupted halt checkpoints without
always closing the durable run.

Required repair: request-scoped lifecycle, pre-start cancellation, provider/worker
interruption semantics, approval wakeup, late-result suppression, effect-aware
termination, and matching durable receipt/run state. A global flag or marking
every cancel request “cancelled” would not satisfy the contract. Task R03.

### A02 — State resolver and launchers disagree

**Source verified; migration prerequisite.**
`core/instance/instance.py:102` resolves JAEGER_HOME through `.jaeger_ai`, performs
initialization/migration, and is called by `USER_ROOT` at import. Its test fallback
is a shared `/tmp/jaeger_test_state`. `run.sh:52` sets JAEGER_HOME and then assigns
JAEGER_STATE_DIR from it. `install.sh:30` also uses JAEGER_HOME for clone location.
These are different meanings of the same variable.

Required repair: pure resolution, explicit startup, separate checkout/state
meaning, documented precedence, migration of actual old layouts, and entry-point
tests. Changing only the Python resolver would miss launcher behavior. Tasks
F01–F04. Do not test migration against the operator's actual state.

### A03 — Admission does not bind all execution choices

**Source verified gap; broader behavioral reproduction still required.**
`core/gateway/server.py:1047` calls `admit_request(session_id, text,
request_id=request_id)`. The store supports an `extra` fingerprint argument but
does not receive the model/provider/attachment choices here. Session model
metadata is updated after admission, including when the request is a replay.

Consequently the existing text/request-ID idempotency check cannot by itself
prove that a retry preserves the original execution settings. Add a reproduction
for changed model/provider and attachment inputs; freeze resolved inputs atomically
at admission and migrate digest semantics without replaying old work. Task R01.
This does not invalidate the passing ordinary model-selection regression.

### A04 — Concurrent request isolation is not established

**Source-derived risk; concurrent failure not reproduced in this audit.**
EntityRuntime rebinds memory/workspace and installs confirmation policy during a
turn. `packages/jaeger-agent/jaeger_agent/memory/sqlite_store.py` keeps a global
connection; `workspace.py` keeps instance/fallback bindings; JaegerOS permissions
use ContextVars plus a process-wide installed-policy fallback.

Sequential tests prove useful behavior, but do not prove that overlapping turns
cannot change each other's confirmation surface, state path, or provider context.
Create interleaving tests, then inject owned dependencies with defined thread
propagation. Tasks F03, R02, T03.

### A05 — A requested configuration name already has a different meaning

**Source verified.** `core/instance/schemas.py:494` already defines RuntimeConfig;
it is the persisted inference-engine settings object, used by Config.runtime.
The original plan's phrase “introduce RuntimeConfig” is too ambiguous for a small
agent.

The new prompt requires preserving that serialized schema and distinguishes an
immutable resolved application snapshot, for example ResolvedRuntimeConfig.
StatePaths has not been established as the injected runtime foundation. Task F01.

### A06 — Existing tool substrate should be evolved

**Source verified.** JaegerOS `core/tools/tool_schema.py:ToolDef` already contains
schemas, toolsets, permission tier, conservative side-effect classification,
availability checks, and examples. `tool_registry.py` is process-global,
registers through import-time decorators, and uses last-write-wins replacement.

JaegerAgent already has ToolExecutor wrappers, effect ledger, run stores, and
verification behavior. PolicyKernel exists in the product. Their presence does
not prove every mutation uses them, but it rules out designing an unrelated
catalog/ledger without first tracing the current path. Tasks T01–T03.

### A07 — Upward dependencies remain concrete

**Source verified.** `mind/cognition/router.py`, `orchestrator.py`, `bridge.py`,
`context_compiler.py`, and `trust_engine.py` import bare WebUI `api.*` modules.
JaegerAgent's `tools/models.py` and `loop/runtime_bridge.py` import JaegerAI product
model/configuration/pipeline helpers.

Required repair: package-neutral interfaces with host implementations, cognition
read/service interfaces, package-qualified imports, and isolated package tests
without the product installed. Moving files without repointing callers is
insufficient. Tasks H01 and F03.

### A08 — Ownership documentation is not an authoritative store inventory

**Source verified mismatch.** `core/state/ownership.py` describes runs/effects
in a separate runs database and semantic memory elsewhere.
`jaeger_agent/cognition/sqlite_runs.py` actually uses the shared sqlite_store
connection, whose bind target is `<layout.memory_dir>/state.db`.

The next agent must inventory connection construction and current schemas,
then correct declarations and design migration. Following the documentation
literally could omit actual data. Tasks B02, F03, F04.

### A09 — A hardcoded persona fallback conflicts with the user requirement

**Source verified; not invoked interactively during this audit.**
`core/instance/setup_wizard.py:514` defaults the display name to `"Jarvis"` when
there is no supplied name or selected persona. This is executable fallback logic,
not merely a comment or optional character preset.

Replace the fallback through the configured naming/identity owner. Preserve
explicit user names, existing entity IDs, personas, transcripts, and character
catalogs. The first-boot files already contain other agents' edits; inspect the
overlap carefully. Task F05.

### A10 — Package default workspace still permits source-tree state

**Source verified.** `jaeger_agent/workspace.py:DefaultWorkspace` defaults to
`Path.cwd() / '.jaeger_agent'`; package runtime code invokes this embedding path.
Tests that set environment overrides cannot establish that a bare embedding is
safe. Repair the default producer and its callers while preserving explicit
project-workspace use. Task F05.

### A11 — Current CI does not implement the claimed qualification boundary

**Source verified.** `.github/workflows/ci.yml` uses raw pytest and Swift test
commands, a narrow critical Ruff selection, and in-tree `dist/all` output.
The safer local runner excludes live acceptance and sets temporary state. The
runner still selects the conventional venv then an in-tree `.venv` fallback.

Swift DispatcherLiveTests call launchctl. Legacy WebUI acceptance intentionally
fails its restart fixture until it is replaced with owned-process lifecycle.
These suites cannot be called complete release evidence as-is. The earlier
Gemini transcript's description of CI edits is not a substitute for the current
workflow contents. Tasks B03, C02, Q01–Q03.

### A12 — WebUI absorption and complete capability preservation remain large tasks

**Source and inventory verified; full runtime parity not verified.**
`features/webui/api/routes.py` is 30,327 lines. Core Gateway is 2,393 lines and
EntityRuntime 993 lines. Size identifies review/extraction candidates, not
permission to remove their behaviors. Static route inventory does not contain
complete response/authentication contracts.

There are 27 feature READMEs. `apps/macos` and `apps/web` are aliases, but iOS
and Swabble are separate trees. Vendor/extension sources include TypeScript and
Rust, contrary to the root document's blanket language claim. Qualification
must be scoped to actual shipped surfaces without deleting optional capabilities.
Tasks B02, H02, H03, C03.

## Original audit verification and limitations — historical

Evidence directory: `/tmp/jaeger-release-prompt-audit.ZEVngTWA`.

| Command scope | Result | Log |
| --- | --- | --- |
| Inventory parser + session model selection + WebUI response contracts, isolated runner unit tier | 22 passed, 7.26s | `focused.log` |
| Real owned Gateway/WebUI process contracts, integration tier | 7 passed, 1 xfailed, 28.11s | `owned-process.log` |
| Static inventory summary | Completed, zero AST parse errors; syntax warnings noted | `inventory-summary.json` |

The full commands are in `RELEASE_AGENT_PROMPT.md` section 14. At this original
snapshot the cancellation expected failure was an unresolved gate, not a success;
Claude subsequently repaired it as recorded in the continuation update above. The worker uses
scripted external model responses; no live provider or operator daemon was used.
No full Python suite, live Swift/browser acceptance, migration, hardware,
dependency audit, or clean release artifact build was rerun for this prompt audit.

Previously recorded broader results remain useful starting evidence, with their
original scope: 4,495 root unit passes under denied networking; 922 agent package
passes; 229 OS passes; 139 Swift offline passes excluding two live tests; 61
production-path passes. The most recent provider-focused run recorded 56 passes.
They are historical, overlap, and do not establish all-client release readiness.

## Changes to the implementation instructions

The original prompt retained M0–M5 and made the execution order concrete with 24
named task rows and a reusable bounded-task packet; revision 2 adds six UI rows.
It preserves current work, records
source-backed defects separately from risks, and requires parity before removal.
It also resolves several ambiguities:

- Existing inference RuntimeConfig versus resolved application configuration.
- Preserving public endpoints versus deleting obsolete internal import shims.
- One durable entity owner versus supported specialist/multiple-instance behavior.
- Session selection versus immutable admitted request input.
- Cancellation requested versus execution stopped versus unknown external effects.
- A durable backup/activation protocol versus an impossible transaction across
  unrelated files and remote systems.
- Test-simulated external behavior versus real device/provider qualification.
- A prepared release artifact versus authorization to publish or deploy it.

Use the technical-debt workflow to prioritize dependency and data/execution
consequences; numeric effort scores would imply precision unsupported by this
audit. There is no defensible fixed credit or completion-time guarantee from
these observations. The practical usage control is to implement one bounded
task, verify it, and hand off its evidence without repeating the whole audit.

## Launch instruction for the next agent

```text
Implement JaegerAI release convergence in the current checkout.
Read docs/architecture/RELEASE_AGENT_PROMPT.md completely, then AGENTS.md and
docs/architecture/RELEASE_AUDIT.md. Inspect the current dirty worktree and
preserve existing edits. Read the prompt's current status in section 3 and the
latest Claude checkpoint. Refresh B01's delta, fill B02/U01 ownership/UI gaps,
then implement the next bounded R02/C01 bridge-to-Gateway migration. Preserve
completed R01/R03 and continue remaining foundation, catalog, UI and release
tasks as their dependencies become ready. Do not restart the audit.
Implement and verify each task, update an external checkpoint, and continue.
Keep one agent active at a time. Do not touch operator state or live services.
Do not call the release complete until the prompt's completion gates are met.
```
