# JaegerAI: complete architectural convergence and release qualification

**Current personal-release entry point (2026-09-23):**
[GROK_PERSONAL_RELEASE_PROMPT.md](GROK_PERSONAL_RELEASE_PROMPT.md).
Its **five-day RC contract** targets a personal companion-assistant candidate by
September 28: reliable IDE/Web conversations, Mac settings/voice/presence, selected
memory and one contextual proactive workflow. Broad worker integration and full
architectural convergence are deferred. It supersedes the older
ordering below, including section 15's continuation instructions. Use this
broader document for contracts and the remaining
convergence backlog, not as a reason to delay the usable fresh-state milestone.

**Latest verified results (2026-09-23):** scratch build stamped and codesigned, `swift_app_is_stale` false, unit 95 passed, owned-process integration 32 passed (browser included), IDE Node 57/58 (1 live-fixture skip), Swift 162 executed/3 skipped/0 failures. Details: [CURRENT_PRODUCT_AUDIT.md](CURRENT_PRODUCT_AUDIT.md). Hardware, live-provider, installed-app and off-LAN gates remain unrun.

This document is a self-contained implementation prompt. Give the entire file
to the implementing agent. Its companion `RELEASE_AUDIT.md` explains the evidence
behind the original findings. Revision 2 incorporates Claude's rounds 3–4 and
the feature-to-UI wiring review, 2026-09-22. Base commit
`917e1eb89b80dafc0524c9e4355a3bae5a56e644`, plus substantial uncommitted work.
The repository may have changed since this snapshot; verify the local delta.
Section 3 is the current continuation baseline. Older audit/checkpoint sections
are historical; do not reopen resolved defects merely because they appear there.

## 1. Assignment and product contract

### Operator scope update — 2026-09-23: fresh-state personal release first

This decision supersedes conflicting historical-data preservation requirements
below. The operator considers most old conversations and memory disposable and
accepts fresh runtime state to obtain a working personal assistant sooner.

- Preserve working code, intended features, tools, skills, client roles, and
  worktree edits. A fresh state/build is not permission for a blank-repository
  rewrite or removal of capabilities.
- Legacy conversations, learned memories, historical identities, and completed
  run receipts need not be imported into the fresh instance. Preserve memory
  functionality and durability for NEW conversations and work. Do not carry old
  schedules, pending actions, or permission grants into a new instance implicitly.
- Prioritize a usable personal-release milestone: configured identity/model,
  real Swift/Web conversation and voice where available, working tools and
  attachments, cancellation, intended background work, real feature UI data,
  and persistence/reconnect/restart in the fresh instance. Retain essential
  permission, state-isolation, and duplicate-action protections. Do not add new
  hardening frameworks without a concrete need.
- Exhaustive legacy migration/upgrade coverage is deferred, not a blocker for
  this fresh-state milestone. Keep existing tested migration code until it can
  be retired safely; do not spend time extending it solely to preserve junk
  history. The broader architecture/Hermes work remains on the completion plan;
  distinguish a usable personal release from full architectural convergence.
- Initially create and test a separate fresh state root outside the checkout.
  Leave existing operator state untouched. Before any later reset/removal,
  resolve exact targets and preserve potentially important material in a dated
  Jaeger archive on the user's actual Desktop. Do not guess that uncertain data
  is disposable: retain its old source or archive it. Verify the archive and
  provide an inventory/restore note; do not copy raw live SQLite files without
  a consistent snapshot. Do not put plaintext credentials or secret-bearing
  config exports on Desktop; retain secure originals and use redacted notes.
- This update does not itself restart services, switch the operator's active
  instance, erase old state, or authorize broad recursive deletion. Prepare a
  fresh instance first and coordinate the actual live cutover separately.

Use meaningful implementation batches with focused regression tests; do not
request a new prompt after every small slice. Preserve broader milestone tests
without repeating the full suite after every edit.

You are implementing the remaining JaegerAI refactor and qualifying its release.
Repository: `/Users/matthewjenkins/GitHub/JaegerAI` on the audited machine.
On another machine, identify the actual checkout; never recreate that user's
absolute directory hierarchy. Read root and applicable nested `AGENTS.md` files.

Deliver a coherent Jaeger-owned application: one persistent entity per configured
entity/instance, with durable identity, memory, ongoing work, tools, permissions,
skills, replaceable models, and multiple clients. Existing specialist agents,
delegation, roundtables, optional cognition, and multiple configured entities
remain supported. “One owner” does not mean deleting specialist identities or
serializing every independent session into one global conversation.

Refactor existing capabilities into clear owners and migrate their callers.
Reuse working implementations where they meet the target contract. Rewrite an
implementation when its ownership or invariants cannot be repaired cleanly.
Do not manufacture a second framework alongside the first and call it convergence.

Preserve all existing product features, tool names and arguments, installed
skills, extension capabilities, new-instance data, client roles, and public WebUI
endpoints. Historical operator data follows the fresh-state decision above.
Record optional/experimental/unavailable capabilities honestly. A capability
that cannot run without credentials or hardware is still part of the inventory;
it must remain discoverable with an accurate availability reason. Do not claim
that its live execution passed when only a simulator ran.

Identity comes from the configured entity and durable identity state. Remove
arbitrary character-name fallbacks from generic runtime and onboarding behavior.
Do not introduce “Jarvis,” “C-3PO,” “ARES,” “Lilith,” or another persona as a
hardcoded generic identity. Preserve names the user deliberately chose, shipped
optional character presets, historical transcripts, provenance, and genuine
third-party protocol identifiers. Do not apply a global text replacement.

The current architecture is mainly Python: JaegerAI product composition,
JaegerAgent's model/tool loop, and JaegerOS foundations; macOS uses Swift.
Inspect each other component's actual stack. Vendor/extension trees also contain
TypeScript, Rust, and other assets. Do not convert languages or rebuild the UI
stack merely to reorganize folders. Self-contained means installable from this
checkout and declared dependencies, without a sibling Hermes source checkout;
it does not mean embedding every external model or cloud service.

Freeze unrelated feature development during convergence. Roadmaps describe
intent; they do not prove an implementation exists or authorize inventing every
future feature. Preserve unfinished roadmap work and distinguish implemented,
partially implemented, and planned capabilities in the inventory.

Success means the implementation is wired into real startup/client paths, old
competing implementations are retired after parity, and the release gates in
section 13 pass. A new class, passing unit test, or folder move alone is not a
completed migration.

## 2. Authority, working state, and usage control

Ordinary scoped source changes, caller updates, deletions of superseded code
after proof, documentation, and isolated tests are authorized. Continue without
repeatedly asking permission for each module. This assignment does not authorize
writing/migrating live operator databases, restarting operator services, spending
on provider calls, sending messages, operating hardware, publishing a release,
or pushing changes. Prepare those steps and report any required final external
action separately. Do not disable product permissions to make acceptance pass.

Use one implementing agent at a time unless the user explicitly authorizes
parallel agents. Claude, GPT, or another agent can take successive task packets.
Never have two agents edit the same worktree concurrently without an agreed
file-ownership plan. The agent maintaining the checkpoint coordinates the work.

Preserve all existing staged, unstaged, and untracked changes. In particular:

- `jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/TTS/VoiceStage.swift` has
  pre-existing user edits.
- `dev/docs/roadmap/0.9.3_EVERYDAY_AGENCY_PLAN.md` is staged work.
- First-boot/setup-wizard/native-turn changes include prior agent work.
- Inventory scripts, fixtures, process harnesses, and convergence docs may still
  be untracked. They are part of the current work, not disposable scratch files.

Inspect overlaps before editing. Do not reset, clean, stash, or overwrite the
worktree to obtain a clean starting point. Do not automatically commit, push,
tag, install into the operator environment, or change the live default model.

Use `apply_patch` for source/document edits. Use the external development venv
or a newly created external scratch venv. No in-repository virtual environments,
runtime state, logs, caches, databases, build scratch, or model downloads.
Set `PYTHONDONTWRITEBYTECODE=1`; redirect Python, pytest, Ruff, Swift, and other
tool caches/build output outside the source tree. Do not hide pollution with
ignore rules. Product workspaces may target a user-selected source project for
authorized coding tasks; internal agent state must still remain outside it.

Create an external task directory with `mktemp -d` or an equivalent unique
directory. Keep `CHECKPOINT.md`, task status, command logs, manifests, temporary
instances, and test reports there. Tell the user its exact path. Curated fixtures,
architecture docs, and source code belong in the repository. Temporary runtime
traces do not. Durable implementation instructions must not depend solely on a
`/tmp` file surviving a restart; keep this specification in the repository.

Read only relevant modules and their callers for each task. Reuse the inventory
and current checkpoint instead of auditing all 19,000 files repeatedly. Run
focused tests while changing a module; expand verification when shared contracts
change or a milestone closes. Test counts are evidence, never quotas. Repeating
green full suites after documentation-only changes wastes usage.

## 3. Verified starting point: retain this work

Resume from the existing implementation. Do not start again from the old 35-test
handoff or the original cancellation expected failure. Claude subsequently added
request-scoped cancellation, immutable admitted execution input, configuration
primitives, a specific legacy-state migration, policy isolation, tool ownership
checks, effect recording, CI alignment, artifact checks, and an operator runbook.
All work remains uncommitted at this revision; preserve it.

Latest implementation checkpoint:
`/tmp/jaeger-convergence.ZELAZ1Ue/CHECKPOINT.md` (read the latest round, not just its
earlier status table). Durable evidence: `docs/architecture/CONVERGENCE.md` and
`docs/OPERATIONS.md`. If temporary logs are unavailable, inspect the code and rerun
the relevant focused checks; do not invent evidence or discard completed work.

The following status distinguishes a verified slice from a complete milestone:

| Task | Current evidence | Remaining scope |
| --- | --- | --- |
| B01 | Baseline manifests/checkpoint exist | Refresh delta, do not redo the audit |
| B02/B03 | Selected boundaries characterized | Full preservation and feature-to-UI matrices remain incomplete |
| F01 | StatePaths and ResolvedRuntimeConfig primitives tested; serialized inference RuntimeConfig retained | Production-wide injection remains under F02/F03; enforce snapshot immutability at its exposed nested values |
| F02 | Eager USER_ROOT removed; shared test path removed; checkout-valued JAEGER_HOME rejected; launcher venv handling improved | operator_state_root still initializes/migrates on resolution; remaining callers and root semantics must converge |
| F03 | Request approval policy scoped with use_policy; cross-thread regression added | Memory/workspace globals and full dependency injection remain |
| F04 | `.jaeger_os` → `.jaeger_ai` migration has lock, backup, manifest, staging, integrity checks, activation and crash-resume tests | This is not all legacy Jaeger/Hermes paths, per-instance schemas, or every rollback/upgrade scenario |
| F05 | Generic character-name fallbacks corrected; obsolete identity/persona modules retired | Standalone DefaultWorkspace still defaults to cwd/.jaeger_agent; full identity upgrade/client parity remains |
| R01 | Admission snapshot, digest versioning, conflict/replay behavior and legacy receipt tests implemented | Preserve and extend these when changing owners/clients |
| R03 | OWNER cancellation interrupts the provider, closes approvals, rejects late approval, persists one outcome, survives restart; expected failure removed | Preserve these gates through R02/C01 and qualify every client/effect case |
| T01 | Conflicting tool owners fail unless replacement is explicit; help_me/reload_skills collisions repaired | Registry remains process-global; instance catalog injection and registration purity remain |
| T03 | Non-read calls record per-invocation intent/outcome; uncertain crash outcomes retained | Exact approval/action binding, independent verification, and external retry reconciliation remain |
| H03 | WebUI no longer auto-adopts a sibling Hermes checkout; explicit override remains | Donor absorption and vendor retirement remain |
| Q01 | Local/CI runner alignment, external CI build paths, import-purity probes and dependency ratchet added | Existing import debt remains; broaden purity coverage and enforcement; actual CI run unobserved |
| Q02 | Ten distributions built/inspected; non-editable packages exercised outside checkout | Test venv reused third-party dependencies via a read-only path entry; fully independent dependency resolution and complete client/upgrade qualification remain |
| Q03 | docs/OPERATIONS.md exists | Extend for final topology, build locations, UI, upgrade and qualified release results |

R02, full T02, A01, H02, full H03, C01–C03, and the new UI tasks remain open.
Completed R01/R03 slices do not imply the canonical execution spine is finished:
Gateway and bridge currently can each own execution for the same entity.

Read these before editing their owners:

| Concern | Existing source/evidence |
| --- | --- |
| Architecture evidence | `docs/architecture/CONVERGENCE.md`, `RELEASE_AUDIT.md` |
| Static inventory | `dev/scripts/architecture_inventory.py`, `dev/tests/test_architecture_inventory.py` |
| Test isolation/tiers | `dev/scripts/run_tests.sh`, `dev/tests/conftest.py`, `.github/workflows/ci.yml` |
| Real owned process | `dev/tests/fixtures/gateway_contract_worker.py`, `dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py` |
| Recovery and admission | `core/gateway/session_store.py`, tests `test_gateway_process_recovery.py`, `test_gateway_durability.py` |
| Current model fix | `core/gateway/server.py`, `core/entity/runtime.py`, `core/models/router.py`, `test_session_model_selection.py` |
| Skills | `packages/jaeger-agent/jaeger_agent/skill_registry/playbook_skills.py`, `skill_audit.py`, `tools/skills.py` |
| Static WebUI fixture | `dev/tests/fixtures/webui_static_dispatch_contract.json` |
| Current admission/cancellation | `core/runtime/cancellation.py`, `test_gateway_admission_snapshot.py`, `test_request_cancellation.py`, current owned-process tests |
| Config/migration | `core/instance/resolved_config.py`, `state_migration.py`, `test_resolved_config.py`, `test_state_migration.py` |
| Existing architecture gates | `dev/tests/test_import_purity.py`, `dev/tests/test_package_layering.py`, `dev/tests/fixtures/package_layering_baseline.json` |
| Tool/effect follow-up | `packages/jaeger-os/dev/tests/jaeger_os/core/test_tool_registry_ownership.py`, `packages/jaeger-agent/tests/runtime/test_local_effect_intent.py` |

Here and below `core/...` means `jaeger_ai/core/...`; bare test basenames in this
table are under `dev/tests/jaeger_ai/core/` unless a full path is supplied.

Latest Claude evidence, reviewed from the checkpoint/logs for this prompt update:
root unit **4,586 passed, 1 skipped, 424 deselected**; Gateway integration **44
passed** (including the now 10-case owned-process suite); security **187**;
production-path **61**; fault injection **5**; Swift offline **139**; packages
agent **933**, OS **290**, Kokoro **10**, Whisper **6**. No failures were reported
in those runs. These are Claude's recorded runs, not new test executions performed
for this documentation update. Counts overlap and have different scopes.

The original 22 focused passes and 7 passes/1 xfail are historical. Do not retain
the old cancellation expected failure. The process harness still scripts the
external provider; Swift live networking, browser JS, production startup, real
hardware/provider behavior, and a GitHub Actions run remain separate gates.

Privacy regression: the deleted `jaeger_agent/tools/safari.py` was an import-time
bookmark-reading/printing script, not a supported registered tool. Preserve its
removal and the regression protection. Never restore it to preserve file counts
or print private browser contents while auditing it. Preserve legitimate browser
capabilities through explicit authorized tool execution. The new import-purity
probe checks selected roots for stdout/files under scratch locations; it is not
yet proof that every import avoids private reads, stderr leaks, networking,
threads, or global registration. Extend it without exposing captured content.

## 4. Concrete defects and traps to resolve

1. **State path semantics:** operator_state_root still creates directories and
   invokes migration and still uses `JAEGER_HOME/.jaeger_ai`. The pure StatePaths
   primitive and JAEGER_HOME checkout guard exist; migrate production callers to
   explicit startup. Explicit JAEGER_STATE_DIR still needs the target no-in-repo
   invariant, and install_root/installer meanings remain to reconcile. Do not
   remove the working legacy migration while completing that transition.
2. **Snapshot integration:** reuse existing ResolvedRuntimeConfig. Its capture
   deep-copies input, but the exposed nested `config` is a mutable Config; a
   frozen dataclass alone does not prevent `snapshot.config` mutation. Verify
   consumers, close that contract, and inject it instead of adding another class.
3. **Global bindings:** per-turn approval-policy leakage has a regression-backed
   fix. Memory/workspace globals remain. Test actual supported concurrent paths
   and isolate dependencies; do not infer either safety or a reproduced failure
   solely from a global variable's presence.
4. **Two production owners:** Gateway resident locking and bridge/TUI InstanceLock
   do not establish one common owner. The native app uses both paths. Preserve
   transports while migrating bridge/TUI execution to Gateway; simply making the
   locks mutually exclusive would break the current client topology.
5. **Admission/cancellation are implemented:** retain snapshot/digest migration,
   no-mutation replay, request-scoped interruption, approval closure, and durable
   terminal behavior. Their existing tests are acceptance gates for R02/C01,
   not instructions to write an independent replacement from scratch.
6. **Upward dependencies and dormant cognition:** remaining package imports are
   recorded by the ratchet; `mind/cognition` was reported unwired. Trace dynamic
   entry points/configuration and map each intended cognition behavior to its
   canonical owner. Preserve intended behavior through owner services; do not
   delete it solely because static import searches find no caller, or resurrect
   a second runtime. Retire only proven duplicates with parity. A genuinely new
   product choice can be isolated for user input without blocking other tasks.
7. **Catalog substrate:** JaegerOS `ToolDef` already has schema, toolset,
   permission tier, side-effect classification, and availability fields.
   `tool_registry.py` now rejects conflicting ownership unless replacement is
   explicit, but remains process-global/import-driven. Keep the new invariant
   and explicit reload_skills override when evolving it into an injected catalog.
8. **State documentation drift:** `core/state/ownership.py` describes locations
   such as a separate runs database, but current SqliteRunStore uses the shared
   `memory/sqlite_store.py` connection to `<memory_dir>/state.db`. Trace actual
   connections before designing migrations. Existing ownership tables are intent
   until their declarations are checked against the implementation.
9. **Onboarding identity:** generic character-name fallbacks have been repaired;
   preserve explicit user names/presets and verify identity across new clients,
   upgrades and state-owner changes. Do not restore retired identity/persona modules.
10. **Standalone workspace:** `jaeger_agent/workspace.py:DefaultWorkspace` uses
    `<cwd>/.jaeger_agent`. Change the producer and embedding startup; a test-only
    environment override cannot fix application state pollution.
11. **CI/build follow-through:** runner/CI alignment and external CI scratch paths
    are implemented. The native `interfaces/swift/Scripts/build-app.sh` still uses
    an in-tree build/app location. Route build and install destinations explicitly
    outside the checkout, updating launch/discovery/docs together. A new external
    build does not authorize deleting/replacing the running operator app.
12. **Qualification gaps:** replace unsafe live restart assumptions, qualify Swift
    networking/browser JS, resolve dependency availability in a fully independent
    install, remove baselined import debt, and complete architecture enforcement.
    The real CI run needs repository workflow authority; its absence does not
    block implementing and locally verifying the remaining code/UI work.
13. **UI truth:** reachable Swift Skills, Tasks, Kanban and Workspace panels use
    sample state; Workspace's Commit action simulates success locally. Existing
    Web panels, finance extension UI and settings must be preserved and connected
    through their owners. Complete section 10's feature-to-surface requirements.

These are starting anchors. Verify current definitions and callers, and add new
findings to the ledger with evidence. Do not remove a capability solely because
one of these descriptions says it is old or derived from another project.

## 5. Target modules, owners, and dependency rules

Retain the established top-level homes. First produce a module ownership map;
then move cohesive implementations and their callers, one slice at a time.

| Home | Owns | Must not own |
| --- | --- | --- |
| `jaeger_ai/contract/` | Product wire DTOs, protocol constants, compatibility versions | Runtime construction, stores, side effects |
| `jaeger_ai/core/instance/` | Product configuration resolution, composition inputs, startup/migration coordination | UI behavior, provider calls during import |
| `jaeger_ai/core/gateway/` | Admission, session/attachment/approval services, durable client events, delivery | Competing model loops or UI business logic |
| `jaeger_ai/core/entity/` | Persistent entity, context, strategy, learning/reflection coordination | HTTP presentation, WebUI imports |
| `jaeger_ai/core/runtime/` | Shared execution coordination and runtime contracts | Independent client-owned runtimes |
| `jaeger_ai/core/models/` | Product provider discovery/configuration/client composition | Entity identity or session storage |
| Existing owning stores | Persistence for their documented domains | Foreign-domain writes through direct SQL |
| `packages/jaeger-os/` | Reusable foundation contracts, policy/OS/tool primitives, device abstraction | Imports of product or WebUI |
| `packages/jaeger-agent/` | Reusable model/tool loop, run/effect/memory abstractions, skills | Imports of product or WebUI |
| TTS/STT packages | Reusable speech engines | Product session ownership |
| `jaeger_ai/features/<feature>/` | Optional domain capability and its service adapters | A second top-level entity/runtime |
| `jaeger_ai/interfaces/`, `clients/` | Client transports, UI/voice presentation, SDK | Direct foreign-store SQL or local production turn execution |
| `integrations/`, `extensions/`, nodes/plugins | External adapters and manifest-driven capabilities | Implicit new state/execution ownership |

Dependency direction: interfaces and product composition depend on application
services; services depend on reusable contracts/packages. Reusable packages do
not import the product. Hosts provide callbacks/protocol implementations for
model discovery, configuration updates, telemetry, and product-only tools.
Shared generic path values may live in JaegerOS; product-specific environment
resolution and configuration remain in the product composition layer. No extra
foundation package is required merely to satisfy the diagram.

`apps/macos` and `apps/web` are symlinks. Edit their targets. `apps/ios` and
`apps/swabble` are separate source trees: inventory and qualify them according to
their actual shipped role. The WebUI can remain physically in `features/webui`
while its handlers become thin transport adapters. A folder move is optional
when ownership can be made clear without it.

For every move, list old owner, new owner, importers, dynamic string imports,
entry points, package data, resource lookups, manifest references, and tests.
Move one implementation; update all callers and delete the old internal path in
the same completed change. No re-export modules or permanent import aliases.
Preserved public HTTP routes, NDJSON commands, and genuinely distinct external
protocols remain valid supported adapters.

## 6. M0: finish the protected map and boundary contracts

Do not restart a whole-repository audit. Complete the gaps using the current
inventory and production-path evidence. A discovered defect can remain an
explicit red gate until its owning refactor; do not spend indefinitely polishing
a legacy path that the approved replacement will remove. Before replacing a
boundary, its inputs, outputs, caller list, and relevant behavior must be recorded.

### M0.1 — Freeze a reproducible starting record

Record commit, dirty-file list, relevant diffs, tools/interpreter versions, and
fixture revision or content hashes. Preserve sensitive values: list credential
variable names and providers, not secret contents. Maintain a separate baseline
manifest and current manifest so an inventory refresh cannot erase a lost feature.

Create task records with ID, owner, dependency IDs, status, source anchors,
changed paths, required tests, test result/log, remaining risk, and next action.
Statuses: `pending`, `active`, `verified`, `blocked_external`. Use `verified` only
after executable evidence and caller migration, not when code was written.

### M0.2 — Complete machine-readable preservation matrices

Extend the existing inventory rather than adding another scanner. Each row must
be assigned an owner, maturity, consumers, replacement, and parity evidence:

- Capability: feature ID, description, source, startup/enable mechanism, callers,
  data domains, tools/skills, dependencies, availability reasons, tests.
- Process/client: launcher, transport, bind/socket, authentication, startup and
  shutdown responsibilities, reconnect/recovery, background delivery.
- Store: physical resolver expression, actual database/file, schema/version,
  readers/writers, leases/locks, lifecycle, migration and backup strategy.
- Tool/skill: stable identity, signature/schema, handler, provenance, permissions,
  effect category, availability, visibility, dynamic registration/reload.
- HTTP/IPC: method/message kind, exact/prefix/computed matcher, request shape,
  validation, authentication, authorization, status, response schema, headers,
  streaming/replay/close semantics, actual consuming client.
- Environment/configuration: key, current meaning, default/precedence, readers,
  startup versus live reload, secret status, target owner, migration treatment.

Every existing feature folder needs coverage, including finance, cost tracking,
CalDAV, channels, dispatcher, missions, scheduler, roundtable, reasoning, shared
memory, knowledge library, history import, session search, skill tree, personality,
voice, remote access, OIDC, passkeys, timeline, cameras/devices, host capabilities,
CLI backends, Agentgateway, operational health, migration features, and WebUI.
Also cover extensions, plugins/nodes, avatar, iOS, Swabble, PySide, package engines,
and external delegation. Inspect actual implementations rather than inferring
support solely from a README or registration name.

The static WebUI fixture covers recognized route patterns only. Expand it with
real dispatcher/handler probes and client tracing until every supported endpoint
has a row. Prefix/dynamic routes need representative and negative cases. Group
similar endpoints into parameterized fixtures, but leave no unexplained rows.

### M0.3 — Make the test boundary trustworthy

Reuse the owned-process worker. Keep real Gateway, EntityRuntime, agent loop,
tools, policy, stores, and WebUI routing. Script external provider/service/device
responses at their adapters. Track every PID created and stop only those PIDs.
Use allocated loopback ports and isolated state. No hardcoded production ports
in tests, no live credentials, no launchctl restarts, no symlink escapes.

Classify failures: product defect, stale assertion, environmental restriction,
test isolation defect, unavailable external dependency, or untested capability.
For a stale assertion, preserve the original security/product invariant and show
behavioral evidence for the corrected assertion. Do not silence failed tests,
broaden xfails, strip features, or replace real internal routing with mocks.

M0 gate: baseline manifests and owner map cover known capabilities; each boundary
about to change has executable contracts; failure ledger is explicit; isolated
test runs cannot touch operator state. Full public-route parity must be complete
before deleting donor routes. Full client acceptance must pass before release.

## 7. M1: configuration, state ownership, migration, and identity

Continue the existing primitives/migration and completed naming fixes from section
3. Requirements below define the full target, including unfinished production
injection and additional migration coverage; they do not reset completed slices.

### M1.1 — Resolve configuration once

Create immutable `StatePaths` values and a resolved application configuration
snapshot using the existing serialized configuration as input. Preserve the
existing inference `RuntimeConfig` fields. A frozen outer object containing
mutable nested dictionaries is insufficient; use immutable nested values or
defensive copies. Session choices are separate mutable domain state and become
immutable request inputs at admission.

Only the designated configuration boundary reads application environment values.
`operator_state_root()` is the product entry to state-root resolution; reusable
packages receive values. Secrets resolve through a credential provider and never
appear in snapshots/logs. Preserve supported live configuration changes through
an owner that validates and publishes a new snapshot.

Target root precedence: explicit `JAEGER_STATE_DIR`, then `JAEGER_HOME` as state
root, then `~/.jaeger`; ignore blank overrides. Preserve named-instance and
explicit-instance selection with documented precedence. Separate checkout
location from state location in installers/launchers. Never overwrite an explicit
state override with a different home-derived value. Test direct CLI, wrapper,
WebUI launcher, service startup, and package embedding separately.

Resolution is pure: no mkdir, database open, migration, registration, subprocess,
or background thread. Remove eager `USER_ROOT` resolution and shared test-path
fallbacks. Explicit startup owns initialization and partial-startup cleanup.
Avoid exposing a new optional config argument while production silently uses
old global values; trace and update every production composition path.

### M1.2 — Inject store/workspace ownership

Use protocols over existing stores for sessions, requests/events, runs/effects,
semantic memory, entity events/identity, attachments, schedules, finance, costs,
and feature data. Route handlers and clients call owners, never open another
owner's database. Keep separate domain databases where appropriate; moving all
tables into one SQLite file is not a prerequisite.

Replace global store/workspace rebinding with runtime-owned instances passed to
the loop, tools, and services. Prove two isolated runtimes cannot swap each other's
connections, roots, policies, credentials, or models. Test fresh OS threads as
well as async tasks; ContextVars alone do not solve all thread propagation.

Standalone embedding must explicitly supply a workspace/state root or use the
documented external user-state default. It must not create `<cwd>/.jaeger_agent`.
Reject internal-state roots within source checkouts after canonicalizing symlinks.
Do not mistake a deliberately selected project workspace for internal state.

Preserve memory semantics, not just table counts: stable entity attribution,
conversation chronology, claim provenance, user preferences, retrieval/index
links, reflections, learned skills, ongoing commitments, and configured retention.
Identify authoritative records versus rebuildable indexes. A model/embedding
provider change may require index rebuild/versioning, but must not erase source
records or convert uncertain claims into facts. New learned skills belong to the
configured state/skill store; they must not silently edit bundled source during
ordinary learning. Explicit authorized coding/self-modification workflows retain
their own approval and audit contract.

### M1.3 — Recoverable legacy migration (deferred for fresh-state release)

The following is the specification for a supported legacy upgrade, not a
prerequisite for the operator's fresh-state release. Mark its remaining work
`deferred_fresh_start`; do not imply that untested upgrades are supported.

Inspect current `core/instance/legacy_state.py` and each store schema before
extending them. Migrate only identified Jaeger-owned locations or explicitly
selected imports. An unrelated `~/.hermes` installation is not free input.

Implement a state machine: discover -> preflight -> lock -> verified backup ->
stage/transform -> verify -> activate -> complete. Persist a versioned manifest
with source/destination identities, schema versions, phase, hashes where useful,
verification results, and rollback location. Never store credentials in it.

Require a quiescent source or a verified consistent snapshot, including WAL data.
Use SQLite backup APIs, not blind copying of an active `.db` file. Check free
space, locks, file ownership/permissions, collisions, corrupt/newer schemas,
attachment references, identities, grants, schedules, indexes, and active runs.
Conflicting identities or same IDs with different data must produce a conflict
report; never silently merge using last-write-wins.

Stage on the destination filesystem; atomically activate a complete generation
or an activation pointer after durable manifest writes. Multiple databases do
not share a magical filesystem transaction. Startup must detect interrupted
activation and refuse to read a mixed generation. Repeating migration resumes
or safely no-ops; interruption at every phase has a defined recovery path.

Retain backups until the operator's retention decision. Retire legacy live-path
fallbacks only after verified activation. Do not recursively erase source state
as a routine cleanup step. Rollback restores a coherent generation; after new
writes, do not silently roll back to an older snapshot and lose them. Document
the forward-repair/export procedure when a destructive rollback is not safe.

Test empty/fresh, legacy-only, already-migrated, partly-migrated, source and target
both populated, corrupt, locked, newer-schema, full-disk/permission failure,
symlink, concurrent migrator, cross-filesystem staging, and crash-at-each-phase
cases using temporary data and disk assertions.

### M1.4 — Identity and naming preservation

Route onboarding defaults through the existing identity/naming owner. Preserve
explicit name > selected preset > configured/default naming policy semantics.
Use a neutral Jaeger default or existing generated-name policy only where no
choice exists; do not regenerate existing identity. Test user rename, custom
persona, preset selection, restart, provider switch, upgrade, and specialist
handoff. Display name, instance directory, and stable entity ID are distinct.

M1 gate: pure import/resolution tests, actual startup wiring, concurrent isolation,
migration/rollback matrix, standalone embedding, identity continuity, and no
repository-state disk assertions pass. Update ownership docs to actual paths.
For the fresh-state milestone, replace legacy migration/identity continuity
requirements with clean onboarding and new-identity persistence across restart;
legacy migration remains explicitly deferred.

## 8. M2: canonical request lifecycle and execution ownership

### M2.1 — Freeze complete request input at admission

Keep Gateway as control-plane owner and resident EntityRuntime as execution
owner. Define typed request/event/result contracts using existing wire fields.
Preserve session/entity/request/run IDs, parent/root lineage, source, selected
model/provider, workspace, attachment references, approval scope, and options.

Atomically validate/admit the request and persist its effective execution input.
Use a deterministic, versioned fingerprint of all execution-affecting fields.
Account for omitted fields resolving from session defaults. Persist that resolved
snapshot; future session changes must not alter an admitted request.

Identical retry returns the same receipt, never re-executes or mutates selection.
Conflicting request-ID reuse returns the established conflict response. Attachment
references/content revisions must not silently change between retries. Preserve
replay of pre-upgrade receipts through a documented digest/version migration;
never reinterpret an old digest as a new schema or replay its side effects.

### M2.2 — One coordinator, durable terminal delivery

Evolve the existing lifecycle/executive/stores. Do not introduce another scheduler
and receipt journal with competing authority. Bind the durable run before the
first effect. Map internal run states to existing public statuses explicitly.
Separate a resumable blocked run, terminal failure, completed work, cancellation,
and an unknown effect outcome.

Persist the terminal result and authoritative event atomically where they share
a store; for cross-store projections use durable delivery/outbox or equivalent
idempotent reconciliation. SSE loss must not lose terminal results or cause a
second execution. Clients reconnect using durable sequence IDs. A provisional
`execution_unknown` recovery observation must have a documented reconciliation
event path; do not emit contradictory terminal answers as independent completions.

Per-session ordering and multi-session worker limits must remain explicit.
Provider selection reaches the actual adapter; tool results and capability claims
must describe real execution. Preserve tool-call repair before schema validation.
No image/vision, text-only, specialist, or error fallback may bypass applicable
authority/effect tracking or silently create another persistent entity.

### M2.3 — Correct cancellation and approval lifecycle

Implement request-scoped cancellation as part of this coordinator:

1. Register cancellation state at admission, before a worker can execute.
2. Bind it to the request/run/agent instance. A global “stop all” flag is wrong.
3. Preserve cancellation requested before agent startup; the loop must not clear
   an externally owned signal when it resets its own per-turn state.
4. Interrupt provider waiting through supported adapter cancellation. A library
   call that cannot be stopped must not resume tool dispatch from a late result.
5. Wake pending approval waits, persist their denial/closure, and reject a late
   approval for a cancelled request. Resolve approval/cancel races atomically.
6. Prevent further dispatch after the signal; handle tools already executing
   according to their effect semantics and timeout/abort capability.
7. Use the effect ledger to decide terminal truth. Pending external effects stay
   unknown until reconciliation. A completed effect remains recorded even when
   the remainder of the turn is cancelled.
8. Transition the durable run and client receipt consistently; release request
   resources and emit a single authoritative outcome.
9. Cleanup must not remove cancellation state while a detached worker can still
   act. Late completion and duplicate cancel calls are idempotent.

Do not treat cancelling an asyncio wrapper around a thread as stopping that
thread. Do not kill shared provider workers or operator processes to simulate it.

The owned-process test now has unconditional passing assertions proving
interruption before normal provider release, a single terminal event, and restart
continuity. Keep them; extend coverage where needed to no late tools and each
new execution/client path. Cover cancel before start,
during provider wait, during approval wait, before a tool, during a controlled
mutation, after effect completion, after terminal result, and in one of two
concurrent sessions. Test late approval, provider failure, repeated cancel, and
client disconnect independently.

### M2.4 — Migrate all execution callers

Find production callers of `run_subordinate_react`, `native_runs`, native turns,
direct provider paths, bridge factories, journal runtimes, and `create_runtime`.
Update the caller map. Shared runtime services can call subordinate model/tool
loops only under the canonical owner; they do not need to make HTTP calls to
themselves. External clients and producers submit through Gateway protocol APIs.

The Gateway daemon is `jaeger gateway daemon` on 8810; external Agentgateway is
`jaeger gateway start` with MCP/A2A proxy ports 8811/8812. Preserve `/health`.
The bridge's AF_UNIX/NDJSON protocol can remain as a translating client endpoint.
An unavailable Gateway yields a clear unavailable/startup result, never a hidden
local entity. Preserve explicit supported standalone package embedding separately.

M2 gate: cancellation, admission/replay, concurrency, recovery, model selection,
attachments, approvals, and real owner routing pass. Each retired branch has zero
production callers and replacement parity evidence. Do not delete unrelated
external-provider or delegation support under the label “legacy.”

## 9. M3: one explicit tool/skill catalog and effect path

### M3.1 — Evolve the existing catalog

Extend JaegerOS ToolDef and replace the global registry with an instance-owned
catalog injected into agent construction/executors. Include canonical name,
owner, origin, argument schema, handler, toolset, effect category, grants,
availability probe, and schema/version information where required.

Decorators may attach inert metadata but must not mutate a live global catalog
at import. Feature registration functions populate it during explicit composition.
Update static decorators, dynamic MCP registrations, skill loaders, hardware
registration, tool discovery, and tests together. Catalog replacement/unregister
and hot reload require explicit ownership rules and in-flight-call behavior.

Duplicate names fail with an actionable owner conflict unless a declared,
versioned override policy authorizes replacement. Existing names required by
external clients remain first-class names backed by one implementation. Migrate
stored internal aliases/workflows before removing redundant internal names;
preserving a supported public name is not a reason to retain duplicated handlers.

### M3.2 — Visibility, availability, and authorization remain distinct

Preserve the full callable skill catalog and scoped prompt catalog already added.
Keep list/describe/load discovery available. Hidden from a particular prompt does
not mean uninstalled or forbidden; unavailable due to a missing dependency does
not mean authorized. Defaults expose relevant tools, with explicit access to the
rest. Preserve beta/experimental opt-ins and subordinate allowlists.

Create representative routing cases for conversation, files, browser/app control,
research, memory, scheduling, messaging, voice, and compound work. Measure selected
schemas and token size, but also successful retrieval/execution. Do not use a
fixed skill count as proof of correctness or force all schemas into every turn.

### M3.3 — Policy, effects, and independent verification

Reuse the existing PolicyKernel, ToolExecutor wrappers, run/effect ledger, and
verification abstractions. Inject product policy through package-neutral contracts.
There must be one authoritative policy decision chain, with provenance, rather
than competing independent allow/deny systems or duplicate approval prompts.

Model-produced calls: repair -> validate -> authorize -> durable effect intent ->
execute -> durable result -> independent verification -> client projection.
The current application contract names `jaeger_ai.core.runtime.tool_repair`.
Preserve its malformed-JSON/fences/Python-literal recovery behavior. If the shared
implementation moves into a reusable package, update every importer, tests, and
the repository's declared contract together; do not create an upward package
import or two subtly different repair implementations to satisfy an old path.
Arguments changed by policy must be revalidated and included in the approval/
effect identity. Approval must bind to the exact request/action/target, not merely
a convenient tool name. Fail closed on unknown mutation metadata or policy errors.

Idempotency is per logical operation, not globally per argument string. Intentional
repeated operations are possible; transport retries and crash replays are not new
intent. Before retrying an uncertain external action, use a supported idempotency
key or authoritative probe. Otherwise preserve an unknown outcome for resolution.
Do not claim exactly-once remote effects from a local SQLite ledger.

Verification must check actual receipts/state/content independently of the model's
success text. Read-only observations need appropriate access and audit rules; do
not invent a mutation for each read. Commands, files, email, finance, hardware,
extensions, browser actions, and background workers must not bypass the common
mutation boundary.

M3 gate: all catalog rows mapped; argument/name parity; explicit startup; isolated
catalogs; dynamic reload; malformed-call recovery; authorization and approval
races; effect crash windows; independent verification; scoped discoverability.
Supported features with unavailable dependencies have truthful diagnostics.

## 10. Client bring-up and autonomous work completion

This completes client/background parts of M2 after M3's catalog/effect contracts
are available. Work one client at a time; retain the passing clients after each.

The feature-to-UI work below is explicitly in the authorized release scope. It
completes interfaces for intended capabilities already present in the product
plan; it does not lift the freeze on unrelated new features. Capability coverage
must include both backend behavior and a usable operator surface.

### 10.1 — Complete the shared owner before duplicating UI behavior

Prioritize R02/C01: make bridge/CLI/TUI execution submit through the Gateway while
preserving bridge messages required by Swift, voice, PySide, and terminal clients.
Use owned Gateway/bridge processes and synthetic provider/device adapters for
actual transport tests. Live networking to a test-owned process is already
authorized; it does not require permission to restart the operator's services.
Build this harness and the migration now. Report a hardware/OS-permission blocker
only for the specific test that cannot run, while completing independent work.

Map each bridge command to its canonical service and retained response/event
contract. Preserve config reads/updates, onboarding, voice control, model listing,
tool approvals, streaming, shutdown and reconnect semantics as well as chat.
A translating bridge may own its listener and client connections; it must not
boot another JaegerAgent/EntityRuntime for product turns. Prove one execution
owner across Swift+TUI+Web and no local fallback when the Gateway is unavailable.

Keep feature services in their proper owners. Mount small route modules through
Gateway composition and authenticated WebUI adapters; do not append all finance,
skills, channels, and mission logic to core/gateway/server.py. An in-process
owner can call an injected service directly; every read need not loop through
HTTP. Clients never open owner databases.

Gateway already exposes runtime capabilities, models/frameworks, agents, handoffs,
requests and attachments as well as turns/approvals. Reuse these contracts.
`/v1/events`, `/v1/skills/tree` and other Gemini-suggested paths are proposals,
not existing endpoints. Inventory existing APIs before adding versioned contracts.
Any new event subscription must enforce entity/profile/authorization scope,
persist or resnapshot consistently, and reconnect without lost/duplicated updates.

### 10.2 — Required feature-to-surface preservation matrix (U01)

Extend B02 with machine-readable UI rows. Each row records:

- capability ID, maturity and evidence of intended behavior;
- authoritative service/store, producing caller and startup/enable path;
- current Swift/Web/other surface, with source paths and navigation reachability;
- state: `wired_source`, `verified_live`, `prototype`, `missing`, or
  `blocked_external` (source wiring alone cannot be called verified live);
- existing/new read/control API, DTO/schema version, error contract and event source;
- entity/session/workspace scope, permissions and credential handling;
- installed/enabled/configured/available/authorized status and unavailable reasons;
- loading, empty, stale/offline, failed, permission-denied, demo, and recovery states;
- supported user actions, durable receipts, destructive-action confirmation;
- applicable client acceptance scenarios, evidence, owner and remaining gap.

Every intended capability needs a discoverable operator entry point: a page,
settings card, inspector, contextual control, or clearly linked existing interface.
It need not have a separate top-level tab in every client. Record deliberate
surface choices and preserve existing access. A feature absent from the native
navigation must not disappear from the preservation matrix.

Seed the matrix with these inspected facts and required outcomes:

| Capability | Observed source state | Required release UI behavior |
| --- | --- | --- |
| Skills/catalog | Swift Features/Skills/SkillsView.swift uses SkillItem.sampleCatalog; Web panels.js already calls /api/skills and content/toggle/save routes | Real installed/discoverable skills, origin, availability, permissions, usage and details; preserve existing Web editing |
| Scheduled work | Swift Features/Tasks/TasksView.swift uses ScheduledTask.sampleTasks; Web already has cron list/history/run/pause/resume | Actual jobs, timezone/next run, state, history, delivery destination; controls change canonical schedule state |
| Kanban/dispatcher | Swift Features/Kanban/KanbanView.swift uses KanbanBoard.sample; separate DispatcherClient and Web dispatcher scripts exist | Real persistent board/task state linked to requests/runs/approvals; no separate UI-only task database |
| Workspace/Git/artifacts | Swift Features/Workspace/WorkspaceView.swift uses WorkspaceSnapshot.sample; performCommit creates a local fake commit/success banner; Web has workspace operations | Actual selected project, files/diffs/artifacts, exact commit selection and backend result; never claim a commit without its receipt |
| Missions | features/missions/service.py models root commitments with goals and plan steps; tools exist | Mission progress, steps, linked runs, blockers, approvals, cancel/pause where implemented; distinguish recorded goals from executing work |
| Memory/knowledge/import | Local memory, knowledge_library, history_import and optional shared_memory/Honcho exist; Web memory panel exists | Search/view/source/scope, corrections/deletion, import reports and indexing state; preserve privacy and distinguish local versus shared data |
| Identity/personality | Swift AgentSettingsHUD already exposes Instance, Character, Traits and settings | Consistent configured identity/name/model separation across clients; preserve existing editors and durable names |
| Usage/budgets | cost_tracking store/tools, usage telemetry and Web insights exist | Per-task/session/provider spend, actual versus estimated/unknown cost, budget limits and stop reasons |
| Connections/channels | Plugins, channel registry/catalog, CLI backends and remote adapters have mixed maturity | Setup/status, explicit credentials replace/revoke, delivery routing and reconnect/error detail; catalogued future adapters must not appear connected |
| Finance | features/finance has read-only MVP semantics; extensions/ares-finance has dashboard assets/manifest and mutation tools; Swift FinanceIntent exists | One coherent view of source, freshness, demo/live data, review inbox/budgets and permitted actions, using existing dashboard/intent behavior |
| Calendar/reminders | CalDAV service/tools and scheduler exist | Account/sync state, agenda, create/edit/cancel where supported, timezone/recurrence and notification destination |
| Autonomy/roundtable | Optional reasoning, heartbeat, missions, delegation and roundtable implementations exist with distinct maturity | Plans, initiated work, assigned participants, budgets, pause controls, tool evidence and decisions; avoid implying unimplemented cognition is active |
| Voice/avatar/devices | Voice engines/settings, avatar/timeline, camera/device modules exist | Input/output devices, listening/speaking state, interrupt/mute, permission/availability, timeline/device controls appropriate to the feature |
| Extensions/MCP/A2A | Extension manifests, nodes/plugins and external tool/protocol adapters exist | Installed/enabled/running/unavailable status, exposed capabilities, grants and lifecycle errors |
| Health/access/recovery | Gateway status, ops_health, approvals, OIDC/passkeys, remote access and recovery facilities exist; some settings already wired | Truthful owner/connection health, approval queue/history, blocked/unknown work, access management and migration/backup diagnostics |

The Swift prototype files are under
`jaeger_ai/interfaces/swift/Sources/JaegerAI/Features/` and are mounted by
`ChatWindow/ChatView.swift`. Web surfaces are under `features/webui/static/`,
with Jaeger overlays under `jaeger_ai/assets/`. Finance's existing dashboard is
`extensions/ares-finance/dashboard/` with its own manifest. Trace actual extension
loading; a manifest declaring a tab does not prove it is running in this install.

### 10.3 — Connect current panels and complete operator controls (U02–U04)

First replace the four reachable Swift sample-backed tabs with injected stores/
view models that call owner services. Keep sample data only in explicit previews,
test fixtures or clearly labelled demo mode. In normal operation, unavailable
data displays an unavailable/empty state. It never falls back to plausible sample
cards or balances. Disable unsupported mutations with a reason until their
backend contract exists. Do not remove the intended panel to satisfy this gate.

For Git commit, select exact files/workspace and use the shared policy/effect
path; display the actual commit ID/result. Do not stage every dirty file implicitly
or create a commit in this operator repository to test the button. Use an owned
temporary Git repository. Task toggles/card moves must persist through refresh
and restart and agree between Swift and Web.

Reuse WebUI skills/memory/tasks/workspace/settings/insights panels. Prefer extending
their adapters and state stores to adding duplicate tabs with different owners.
Suggested navigation groups are Conversation, Work, Memory, Capabilities,
Connections, Finance, and Settings/Activity; preserve established affordances
when a different grouping is clearer. No requirement to add 27 top-level tabs.

Make active work, pending approvals, blocked outcomes, budget limits and connection
failures discoverable before adding decorative visualizations. Bind approvals to
the exact request/action/target; all clients display the same decision and late
responses obey existing conflict semantics. Expose plans, tool calls, receipts and
verification evidence as operational explanations rather than invented thinking.

Credential forms use a backend credential service, authenticated/authorized writes,
redacted read responses and explicit replace/revoke semantics. Do not place tokens
in URLs, browser local storage, SSE payloads or ordinary config snapshots. Respect
existing Keychain/secret-store ownership and first-time OS permission flows.
Distinguish plugin installed, adapter implemented, configured, connected, reachable,
and authorized. A catalog entry is not a working transport.

Finance U04 must reconcile core and extension capability/policy contracts before
adding controls. Preserve the extension's intended authorized operations and core
read-only restrictions under explicit capabilities; do not silently enable all
mutations or delete them to simplify the interface. Keep money-movement policy.
Display provenance, last sync, currency and demo/stale status. Unknown balances
must not render as zero. Test with synthetic records and recording provider
adapters; no live Monarch mutation. Native finance intents remain supported.

### 10.4 — Skills progression, learning, autonomy and devices (U05)

Treat callable tools, installed skill documents, learned skills/notes, and the
XP progression graph as related but different records. Reuse existing SkillNode/
SkillTree/XpAward schemas; map them explicitly to wire DTOs and Swift Decodable
types. Do not invent a second progression schema with conflicting meanings.

`features/skill_tree/xp_emitter.py` consumes XP awards and projects graph events;
it is not proof that every tool dispatch produces XP. The inspected code has
animation awards and CLI graph access, but general Gateway tool execution still
needs proven composition/instrumentation. Define the capability-to-node mapping,
when an award is earned, and its durable source event. Verify a real canonical
tool execution updates the expected node, survives restart, and appears in both
clients. Replay/retry must not award XP twice. Do not award success for failed,
denied or cancelled operations without an explicit legitimate learning rule.

Skill usage/XP is not a benchmark of model intelligence or proof of training.
Progression unlocks must not silently install code, enable hardware, or grant
permissions. Show available prerequisites separately from authorization and
dependency availability. A “mastered” label reflects the configured progression
rule, not a claim of independently verified general competence.

Expose skill notes/review state and learned-skill provenance. Add a tree/graph
visualization only after the underlying list, data contracts and events are live.
Preserve experimental opt-ins: autonomy and device views explain capability
availability and supported controls, rather than activating dormant loops on
opening the page. Timeline/avatar controls use their existing owners.

### 10.5 — UI acceptance gate (U06)

For each applicable matrix row, run actual Swift networking or browser interaction
against owned services with scripted external boundaries. A Swift build or DOM
element's existence is insufficient. Require:

1. A recognizable synthetic backend record appears with the right identity,
   scope, content and provenance, without sample-data substitution.
2. An allowed user action reaches the owner once, returns a real receipt, and
   changes durable state; denied/conflicting/failed actions report the truth.
3. Refresh, client reconnect and owned-service restart preserve/reconcile state.
4. A second client sees the same outcome; another entity/workspace stays isolated.
5. Loading/empty/offline/stale/error/unavailable/demo states are distinguishable.
6. Event replay/reordering does not duplicate tasks, approvals, spend or XP.
7. Secrets/private records do not leak through logs, unrelated profiles or events.
8. Keyboard navigation, accessible control names and readable status/error text
   remain usable; essential state is not represented by color alone.

Read-only rows omit mutation tests with a stated reason. Hardware-dependent rows
include simulator evidence and explicit remaining live checks. U06 must cover
the four existing Swift prototype tabs and applicable existing Web panels before
release; graph animation or visual polish cannot substitute for these gates.

### 10.6 — Transport and background completion

Bring-up order: CLI/Python client -> WebUI proxy -> Swift -> TUI/PySide -> voice/
messaging/channels -> MCP/A2A -> iOS/Swabble/avatar and other discovered clients.
Adjust only for real dependencies and record why. Every external transport uses
the same authoritative session/request services, even if its wire format differs.

For each applicable client, test real conversation, incremental events, terminal
delivery, reconnect/replay, cancellation, attachment upload/access, approval allow/
deny/expiry, model/provider choice, memory visibility, restart continuity, and
background completion. Mark a scenario not applicable with a specific reason
(e.g. a read-only display), not a blanket skip for the entire client.

Swift requires live networking to the isolated worker plus unit tests. Web requires
browser JavaScript in addition to Python handler tests. Voice requires mocked
STT/TTS transport contracts and a separately recorded microphone/speaker/device
qualification. Headless clients must surface approvals to a supported UI or queue
them visibly; they must not require a tty, silently approve, or hang indefinitely.

Messaging/email tests use recording adapters; prove permissions, target binding,
delivery receipts, and retries without sending real messages. MCP/A2A preserve
existing method/tool schemas, authentication, streaming where applicable, and
failure semantics. Existing external delegation remains subordinate to the run.

Converge dispatcher, cron/scheduler, missions, heartbeats, and autonomous reasoning
on shared durable runs. A schedule is a producer of runs, a mission groups runs,
and a heartbeat trigger is not another session engine. Preserve timezone/DST,
recurrence, misfire policy, max concurrency, quotas/budgets, cancellation, parent/
child lineage, retries, and delivery destinations. Optional reasoning/roundtable/
device producers submit work with the correct authority and budgets.

Background evidence must include completion while a client is closed, delivery
after reconnect, process death between completion and notification, duplicate
trigger delivery, missed schedule occurrences, and cancellation of one job without
affecting another. Finish migration before deleting old schedulers/executors.

Qualify these operator-visible journeys with recorded outcomes, using existing
capabilities rather than creating unrelated new features:

| Journey | Required observable result |
| --- | --- |
| Name/configure the assistant, restart, switch model | Same entity ID and chosen name; preferences retained |
| Tell the assistant a preference in Web, ask in Swift | Authorized memory retrieval with correct attribution and configured scope |
| Start a turn, close the client, reopen it | Work and ordered durable events recover without a second execution |
| Choose a different provider/model for one session | Actual adapter matches; other sessions and instance defaults unchanged |
| Ask for a file operation requiring approval | Correct client approval; verified disk result; denial leaves no mutation |
| Cancel during a slow model call or approval | Correct request stops; approval closes; other sessions continue |
| Ask an existing browser/app-control skill to act | Tool executes through policy, or explains the exact unavailable permission/dependency |
| Submit an existing reminder/mission/background job | One durable run/delivery chain survives restart and client absence |
| Attach a document or image, then reference it after restart | Authorized attachment access and actual modality support, no fabricated inspection |
| Use voice, then interrupt and continue | Transcript/turn ownership remains coherent; permissions and speech availability are explicit |
| Lose network/provider access and recover | Bounded retry/fallback according to config; no identity loss or silent paid-provider switch |
| Restart after a controlled external effect loses its response | Reconciliation or honest unknown result; no blind duplicate effect |

For integrations unavailable on the test host, preserve the implementation and
run an adapter simulation; record the remaining live verification separately.
These journeys complement per-route contracts and cannot replace endpoint parity.

## 11. M4: Hermes absorption and WebUI decomposition

Classify each donor capability as live, optional, experimental, reference-only,
or already replaced. Preserve useful implementations and licenses. A directory
name or import count is insufficient evidence that code is unused.

Map donor behavior to Jaeger owners: auth/identity sessions, provider discovery,
streaming, history import, workspace/files/git operations, terminal/background
processes, schedules, knowledge/search, extensions/plugins, skills, and browser
presentation. Include settings, OIDC/passkeys, uploads/downloads, mobile consumers,
and configuration migration. Do not discard peripheral capabilities to achieve a
smaller vendor tree.

Extract in dependency order. First supply Jaeger-owned service interfaces, then
move one implementation, adapt its consumers, test, and remove its old internal
definition. Break `api/routes.py` into route groups delegating to these services.
Break other large modules by responsibility and lifecycle; splitting every 500
lines into a file without separating ownership does not meet this requirement.

Replace `mind/cognition` journal/settings/backend imports with injected readers or
services. Move product hooks out of reusable packages. Use package-qualified
imports; remove sys.path-based alias tricks once all consumers are migrated.

All existing supported HTTP endpoints remain contractual: method/path matching,
status, validation/errors, authentication/authorization, cookies, CSRF, OIDC,
passkeys, headers, JSON shape, ordering, uploads, downloads, streaming and replay.
Preserve domain meaning, not known security exploits: fix a demonstrated
vulnerability with a documented compatibility change and negative tests.

Port environment/settings semantics through the M1 migration/configuration
boundary. Remove donor-only runtime variables only after their behavior and
settings have a Jaeger-owned replacement. Keep intentional external Hermes
integration/protocol names where required by that independent product.

For each vendor component deletion, require: replacement owner; all production
callers moved; contracts passing; installed-package/resource tests passing;
license/provenance retained; no unresolved preservation rows. Remove the entire
`jaeger_ai/vendor/hermes_agent` tree only after these conditions hold for every
retained capability. Donor tests may be retired only when the appropriate
Jaeger-owned regression protection exists or their source is proven unshipped.

M4 gate: no product runtime dependency on the retired vendor tree or a sibling
checkout; all preserved feature/HTTP rows have parity; clean installed assets and
extension loading work; no old internal forwarding modules remain.

## 12. M5: architecture enforcement, packaging, and release gates

Add executable gates incrementally as each invariant becomes enforceable:

- Imports create no files, databases, threads, servers, migrations, or live tool
  registrations. Test in fresh processes with denied writes/network; do not fake
  import purity by monkeypatching every filesystem call into a no-op.
- Runtime state cannot be placed inside the repository; test direct entry points,
  symlink paths, working-directory changes, standalone embedding, and launchers.
- Environment/secret resolution occurs only in designated configuration and
  credential adapters. Use AST/import checks with precise exceptions for tests,
  migration input discovery, and external skill scripts with their own contract.
- No core/mind/package imports of WebUI; no reusable-package imports of JaegerAI;
  no UI or protocol client's direct access to another owner's database.
- One canonical production request execution entry, explicit catalog composition,
  unique tool ownership, and complete mutation metadata.
- Preserved endpoint/tool/skill/capability manifests and feature READMEs.
- Module growth limits tied to ownership, with small documented exceptions;
  enforce no new monolith growth while existing extractions complete.

Use graph/AST checks plus runtime tests; keyword bans across vendor examples are
not architecture proof. Do not hide failures behind blanket ignores, dynamic
imports, mocks, markers, or reduced fixture coverage.

Align CI with the local runner's isolation and exact tier semantics. Linux jobs
must not accidentally run macOS/operator-service tests. Swift builds use external
scratch paths; live tests launch owned fixtures or stay explicitly unqualified.
Run root, JaegerAgent, JaegerOS, Kokoro, and Whisper suites in appropriate separate
processes. The updated runner covers all four package suites in its full default
run; the unit-only tier does not. Retain explicit package-suite evidence,
including both speech packages, when qualifying a release.

Configure Ruff consistently and a type checker for first-party Python. Exclude
only justified generated/donor code; ratchet existing findings down with visible
ownership. Do not enable mutually incompatible lint rules merely to claim “all
rules.” Preserve Swift compiler/test qualification and actual JS/extension build
checks where those stacks exist. Audit dependencies and explain any unresolved
advisory exceptions with scope, mitigation, owner, and review date.

Build all distributions into external output directories using a clean external
source copy containing current authorized changes. Inspect artifacts with
`dev/scripts/inspect_release_artifacts.py`. Verify package resources, WebUI static
assets, skills, schemas, extension manifests, Swift resources, and notices. Install
the built artifacts into an external environment with no checkout PYTHONPATH to
catch editable-install masking. Test the supported editable installation too.
Prove no caches, secrets, personal databases, model weights, or retired vendor
implementation ship accidentally.

Qualify a fresh install, upgrade from synthetic legacy fixtures, repeated startup,
crash recovery, sleep/wake and offline/provider-unavailable behavior where
supported, and bounded concurrent-client/background load. Measure resource growth,
queue/backpressure behavior, startup failures, and worker shutdown. Establish
measured acceptance thresholds from the baseline; do not invent passing numbers.

Prepare operator documentation: install, upgrade, data backup, migration report,
restore/rollback boundaries, diagnostic commands, missing-dependency remedies,
provider setup, client startup, and external permission setup. Update architecture
and topology docs from observed behavior. The current docs' blanket claim that
no TypeScript or Rust exists anywhere is inaccurate for the full vendor tree;
scope language/stack statements to the actual shipped surfaces.

## 13. Exact completion rules

Track each gate as `pass`, `fail`, `blocked_external`, or `not_run`, with command,
revision, result, and evidence path. An expected failure is a failure for a
required release gate. A successful compile is not a conversation test.
For the personal fresh-state milestone, record legacy upgrade requirements as
`deferred_fresh_start` and apply section 1's precedence. The table below still
defines full convergence; distinguish that from the usable personal milestone.

| Gate | Required evidence |
| --- | --- |
| Capability preservation | Baseline-to-current row comparison, no unexplained missing features/tools/skills/endpoints |
| Configuration/state | Pure resolution/import, production injection, concurrent-instance isolation, clean disk assertions |
| Migration | Deferred for fresh-state personal release; for supported legacy upgrades: phase/crash/conflict tests, preserved selected data, verified backup/activation/recovery |
| Execution | Actual Gateway/EntityRuntime/agent path, complete admission input, truthful durable results |
| Cancellation/approvals | No expected failure; interruption/late-result/approval-race/effect uncertainty tests |
| Tool effects | Policy/grants, intent/result/verification, malformed arguments, idempotency and crash reconciliation |
| Clients | Applicable acceptance matrix for each shipped surface, real Swift networking and browser JS |
| Feature UI | Complete feature-to-surface matrix; four Swift prototype tabs use authoritative data; existing Web panels preserved; U06 evidence for each applicable row |
| Autonomy/background | One run lifecycle, budgets, schedule semantics, restart and delivery idempotency |
| Hermes absorption | Parity matrix complete, no runtime vendor dependency, attribution retained |
| Architecture/CI | Enforced dependency/store/env/import/registration rules, lint/types, appropriate full suites |
| Artifacts | Clean build/install, contents inspection, resources/skills intact, editable and installed behavior |
| Release operation | Upgrade/recovery runbook, measured resilience, explicit external/hardware checks |

Do not label the full repo release complete while a required gate is failing or
untested. Optional hardware/integration live checks may be reported as externally
blocked only with their simulated coverage, preserved implementation, and exact
unverified claim. Do not call that a fully qualified all-capability release.
Finish all independent authorized work before reporting a remaining external
blocker. Publishing/signing/deploying requires the applicable credentials and
authority; code qualification and a prepared artifact are distinct from release
publication.

## 14. Test commands and execution cautions

These commands were valid at the audit snapshot. Inspect the runner first; as it
is refactored, update the commands and docs together. Never substitute a bare
`pytest` or `swift test` that can collect operator-facing live tests by accident.

Fast initial validation:

```bash
dev/scripts/run_tests.sh --unit -- \
  dev/tests/test_architecture_inventory.py \
  dev/tests/jaeger_ai/core/test_session_model_selection.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_convergence_http_contract.py \
  --tb=short

dev/scripts/run_tests.sh --integration -- \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py --tb=short
```

Current milestone-level commands after test isolation is inspected:

```bash
dev/scripts/run_tests.sh --unit
dev/scripts/run_tests.sh --production-path
dev/scripts/run_tests.sh --security
dev/scripts/run_tests.sh --fault-injection
dev/scripts/run_tests.sh --integration -- \
  dev/tests/jaeger_ai/core/test_gateway_daemon.py \
  dev/tests/jaeger_ai/core/test_gateway_process_recovery.py \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py
git diff --check
bash -n dev/scripts/run_tests.sh
```

Current explicit package commands (one process/root per package):

```bash
dev/scripts/run_tests.sh --package agent
dev/scripts/run_tests.sh --package os
dev/scripts/run_tests.sh --package kokoro
dev/scripts/run_tests.sh --package whisper
```

`--unit` currently omits package suites; the default runner now includes all four
package suites, including speech. `--full` excludes live acceptance but
is not guaranteed to make every legacy integration test safe; inspect its selected
tests before using it. Credentials being unset does not itself disable network.
Use OS-level network isolation or an enforced test network policy for hermetic
tiers, allowing only owned listeners for integration when needed.

Swift offline example, with a freshly allocated external scratch directory:

```bash
swift test --package-path jaeger_ai/interfaces/swift \
  --scratch-path /absolute/external/task-root/swift-build \
  --skip DispatcherLiveTests
```

Substitute the real task-root path. Verify current Swift CLI options. This
exclusion is temporary historical safety, not the final client release gate.
Migrate DispatcherLiveTests and legacy WebUI restart tests to owned fixtures,
then run their replacement acceptance suite explicitly.

Archive stdout/stderr, exit status, selected/deselected/skipped/xfail counts,
duration, environment policy, and source revision. Test state must be unique and
must not read operator credentials, live DBs, active-instance files, or launch
state. Preserve intentionally tested environment-precedence cases inside fixtures.

## 15. Ordered task queue and handoff protocol

Maintain this queue with concrete child tasks when a row is too large. A child
task has one owner/boundary, actual callers, executable tests, and a deletion or
cutover decision. Do not assign “fix architecture” as a small-agent task.

This is a target dependency map, not a claim all rows are still pending. Apply
section 3's current status before selecting work. R01/R03 and other verified
slices landed before full dependencies closed; keep them and extend their tests.
For the next continuation, refresh B01's delta, complete the relevant B02/U01
owner/UI map, and take a bounded R02/C01 bridge-to-Gateway slice with owned-process
acceptance. F02/F03 injection and the remaining migration work continue alongside
that dependency work sequentially. Do not recreate ResolvedRuntimeConfig, redo
the completed cancellation repair, or postpone all UI wiring until vendor deletion.

| ID | Deliverable | Dependency |
| --- | --- | --- |
| B01 | Current checkpoint, dirty-work preservation, baseline hashes | None |
| B02 | Capability/store/process/env/endpoint/tool owner matrices | B01 |
| B03 | Contracts for first foundation cutover, failure classification | B02 |
| F01 | Resolved config/StatePaths + existing schema compatibility | B03 |
| F02 | Pure startup/resolver and launcher precedence | F01 |
| F03 | Explicit stores/workspaces/credentials/policy injection | F02 |
| F04 | Existing migration retained; broader legacy migration deferred for fresh-state release; archive/reset preparation only when needed | F03 |
| F05 | Fresh identity/onboarding and standalone-state convergence; legacy identity import optional | F01; F04 only for a selected legacy upgrade |
| R01 | Complete immutable admission input + digest/replay migration | F03, B03 |
| R02 | Canonical coordinator/run/event ownership | R01 |
| R03 | Request cancellation + approval/effect-aware termination | R02 |
| T01 | Explicit instance catalog over existing ToolDef | F03, B02 |
| T02 | Discovery/scoping/hot reload and metadata parity | T01 |
| T03 | Injected policy/effect/verification chain and crash semantics | T01, R02 |
| C01 | CLI/SDK/bridge caller migration | R03, T03 |
| C02 | Web and Swift acceptance/cutover | C01, T02 |
| C03 | Remaining transport and device/client contracts | C01, T02 |
| U01 | Feature-to-surface matrix, truthful prototype/demo states and per-surface contracts | B01, relevant B02 ownership rows |
| U02 | Wire existing Swift Skills/Tasks/Kanban/Workspace and retain Web equivalents | U01, relevant C01/R02 services, T01/T02 for catalog operations |
| U03 | Complete memory, work/approval, connection, identity, budget and health controls | U01, corresponding canonical owner APIs; R03 preserved |
| U04 | Reconcile finance core/extension capabilities and connect coherent UI/intents | U01, T03 policy/effects, finance owner/provenance contracts |
| U05 | Wire progression/learning events and optional autonomy/device inspectors | U01, T02/T03; A01 for autonomous work; existing device protocols |
| U06 | Real Swift/browser feature interaction, persistence, replay and cross-client UI acceptance | U02–U05, applicable C02/C03 |
| A01 | Schedules/missions/dispatcher/heartbeat shared lifecycle | R03, T03 |
| H01 | Remove mind/package upward dependencies through owner services | F03, R02 |
| H02 | WebUI service/route extractions with complete public parity | H01, C02, B02 |
| H03 | Donor capability absorption, imports/resources/env cleanup | H02, T02, A01 |
| Q01 | Enforce architecture and align CI | Incrementally after each corresponding cutover |
| Q02 | Full suites, clean artifacts/install/upgrade, resilience | F05, C02, C03, U06, A01, H03, Q01 |
| Q03 | Release evidence/runbook and exact remaining external actions | Q02 |

Tests for each client's relevant boundary must precede its implementation move.
Client acceptance and producer migration can be interleaved when interfaces are
stable; do not force artificial cycles in this queue. Q01 begins early and closes
only once every target invariant is enforced. M0's final preservation coverage
cannot remain incomplete at H03/Q02.

U01 can proceed immediately as source/contract work. U02–U05 each migrate one
capability after its owner interface is protected, rather than waiting for every
API in the whole repo. If a corresponding owner is unfinished, implement/test that
owner boundary first; do not build a UI-specific duplicate backend or mock success.

Use this task packet when handing a bounded slice to another agent:

```text
TASK: <queue ID and concrete outcome>
CHECKOUT: <actual absolute path>
SPEC: docs/architecture/RELEASE_AGENT_PROMPT.md
CHECKPOINT: <external absolute path>
BASELINE: <commit plus current relevant dirty-file/hash record>
DEPENDENCIES VERIFIED: <task IDs and evidence paths>
READ FIRST: <specific source owners, caller files, relevant AGENTS.md>
CURRENT BEHAVIOR: <observed trigger/result and test>
REQUIRED BEHAVIOR: <inputs, outputs, ownership, failure/recovery semantics>
SURFACE CONTRACT: <app navigation, owner/API/event, loading/error/demo states, actions; N/A for non-UI task>
EDIT SCOPE: <owner plus required callers/tests/resources>
PRESERVE: <public contracts and overlapping user edits>
IMPLEMENT: <ordered bounded steps; use existing abstractions>
VERIFY: <exact focused commands and behavioral assertions>
CUTOVER/DELETE: <which caller switches and old definition retires, or why not yet>
DONE WHEN: <production wiring plus executable gates>
RETURN: <changed files, exact evidence, remaining failures, next queue task>
```

The implementing agent reads this complete specification once, then the task
packet and relevant code. Keep the checkpoint small enough to resume without
reprinting the whole repository. At each completed slice record what changed,
why, actual test results, migration/rollback consequences, parity rows updated,
and the exact next task. Preserve all unresolved failures in the ledger.

If a task fails three attempts for the same reason, reduce it to a minimal
reproduction and isolate the missing assumption. Continue independent work when
possible. Request stronger review or external information only for the specific
unresolved problem; do not restart the entire refactor or weaken the gate.

Do not promise a duration, credit consumption, or automatic production quality
based on the number of prompts. Control usage by bounded tasks, reusable context,
targeted tests, and explicit completion evidence.

Resume from section 3 and the latest checkpoint. Update the current delta and
B02/U01 preservation gaps, then implement a bounded R02/C01 ownership migration
with its actual client contracts. Complete remaining F02/F03/F04/F05 requirements
and U02–U06 as their owner dependencies become ready. Treat native external build
paths and owned Swift/TUI testing as authorized implementation work; only an
actual unavailable credential/device/service authority blocks its dependent check.
Do not reply with another broad plan in place of implementation. Continue through
the remaining queue and report completion only under section 13's rules.
