# JaegerAI documentation

The current product definition is [`PRODUCT.md`](PRODUCT.md). Read it before
starting release-path work or writing another plan. The stack is in
[`STACK.md`](STACK.md), on-device trust in [`TRUST.md`](TRUST.md), and the
proactive / world-model paper library in [`research/README.md`](research/README.md).

Removed from this repo on 2026-10-22, per the operator's cleanup instruction, and moved to the Desktop (NOT deleted) in `JaegerAI-removed-junk-2026-10-22/`: the older entry-point file docs/PRODUCT.md (55,749 bytes, previously listed as entry point, superseded by PRODUCT.md — its contents were NOT followed in this cleanup), the five dated NATIVE_*.md repair docs, and the two huge integration ledgers MAC_APP_COMPLETION.md (290,290 bytes) and BLUEPRINT_LEDGER.csv (371,325 bytes). See CLEANUP.md for the full list. Nothing in that Desktop folder is an archive in the repo, by preference.
Originals of the docs edited on 2026-10-22 are NOT in this repo, by
preference — archives in the repo confuse people. They are on the Desktop
in `JaegerAI-checkpoint-2026-10-22/`.

Operator instructions live in the root [README](../README.md) and
[COMMANDS.md](COMMANDS.md); contributor workflow lives in
[CONTRIBUTING.md](../CONTRIBUTING.md).

| Document | Classification | Purpose |
| --- | --- | --- |
| [PRODUCT.md](PRODUCT.md) | CURRENT AUTHORITATIVE | Current product definition: standalone intelligence, companion + operator, Jenkins Robotics, humanoid direction, JROS, Aether, NAS, YouTube, cloud today / on-device goal |
| [STACK.md](STACK.md) | CURRENT REFERENCE | Centre = jaeger-agent + JaegerAI on top, stack layers, dependencies |
| [TRUST.md](TRUST.md) | CURRENT REFERENCE | On-device trust: what stays, what leaves, what never leaves without a separate yes |
| [REBUILD.md](REBUILD.md) | CURRENT REFERENCE | 2026-10-22 rebuild: backup, clean restore, 8 jaeger-agent modules |
| [CLEANUP.md](CLEANUP.md) | CURRENT REFERENCE | 2026-10-22 cleanup: junk removed to Desktop, docs realigned, what only an IDE coding agent can do next |
| [research/README.md](research/README.md) | CURRENT REFERENCE | Proactive / world-model paper library |
| [COMMANDS.md](COMMANDS.md) | CURRENT REFERENCE | Operator CLI commands and subcommands |
| [OPERATIONS.md](OPERATIONS.md) | CURRENT REFERENCE | State roots, upgrades, backups, cancellation, retry, and health |
| [RELEASE_0.13.md](RELEASE_0.13.md) | RELEASE RECORD | 0.13.0 qualification, verification gates, and packaging evidence |
| [gateway-task-ownership.md](gateway-task-ownership.md) | CURRENT REFERENCE | Gateway-owned durable background work |
| [EXTENSION_GUIDE.md](EXTENSION_GUIDE.md) | CURRENT AUTHORITATIVE | Public capability, provider, and device contracts |
| [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | CURRENT AUTHORITATIVE | Topology and ownership, with IMPLEMENTED / EXPERIMENTAL / PLANNED status |
| [architecture/MAIN_LOOP.md](architecture/MAIN_LOOP.md) | CURRENT AUTHORITATIVE | One Gateway turn path |
| [architecture/PRODUCTION_PATHS.md](architecture/PRODUCTION_PATHS.md) | CURRENT AUTHORITATIVE | Single production runtime path, invariants, and ownership |
| [architecture/STATE_OWNERSHIP_MAP.md](architecture/STATE_OWNERSHIP_MAP.md) | CURRENT AUTHORITATIVE | One authoritative owner per fact |
| [architecture/STRUCTURE.md](architecture/STRUCTURE.md) | CURRENT REFERENCE | System directory map and component boundaries |
| [architecture/TEST_ARCHITECTURE.md](architecture/TEST_ARCHITECTURE.md) | CURRENT AUTHORITATIVE | What each test tier proves |
| [architecture/THREAT_MODEL.md](architecture/THREAT_MODEL.md) | CURRENT AUTHORITATIVE | Trust domains and mitigations |
| [architecture/DONOR_PROVENANCE.md](architecture/DONOR_PROVENANCE.md) | CURRENT REFERENCE | Donor sources, licenses, and decision records |
| [architecture/adr/](architecture/adr/) | CURRENT REFERENCE | Accepted architectural decisions |
| [architecture/IDE_FIRST_PRODUCT_DIRECTION.md](architecture/IDE_FIRST_PRODUCT_DIRECTION.md) | HISTORICAL | Old IDE product direction and worker requirements |
| [architecture/CAPABILITY_EQUIVALENCE_AUDIT.md](architecture/CAPABILITY_EQUIVALENCE_AUDIT.md) | HISTORICAL | Old capability-equivalence audit |
| [architecture/CODEX_PARITY_BACKLOG.md](architecture/CODEX_PARITY_BACKLOG.md) | BACKLOG / DEFERRED | Selective Codex parity ideas |
| [benchmarks/chronicler-trial.md](benchmarks/chronicler-trial.md) | HISTORICAL | Dated benchmark evidence |

Historical files remain as evidence only. They may reference old dates, branches,
HEADs, dirty worktrees, or acceptance schedules; none of that describes the current
checkout or authorizes skipping current source inspection.

The following stale execution/audit ledgers were removed from the active tree on
2026-09-24; Git history preserves them:

- `docs/architecture/CURRENT_PRODUCT_AUDIT.md`
- `docs/architecture/MASTER_PROGRAM_STATUS.md`
- `docs/architecture/GROK_PERSONAL_RELEASE_PROMPT.md`
- `docs/architecture/RELEASE_AGENT_PROMPT.md`
- `docs/architecture/CONVERGENCE.md`
- `docs/architecture/RELEASE_AUDIT.md`
- `docs/architecture/UI_EXPLORATORY_AGENT_PROMPT.md`

Component docs stay with their code: [JaegerAgent](../packages/jaeger-agent/README.md),
[JaegerOS](../packages/jaeger-os/README.md),
[WebUI](../jaeger_ai/features/webui/README.md),
[Mac menu bar shell](../jaeger_ai/interfaces/macos-shell/REUSE.md),
[IDE client](../jaeger_ai/interfaces/ide/README.md),
and module registrations in [jaeger_ai/modules/MODULES.md](../jaeger_ai/modules/MODULES.md).
The old path jaeger_ai/interfaces/swift/ no longer exists in the repo — it was refactored into macos-shell, and its archive copy is on the Desktop in Jaeger-UI-Archive-2026-10-17/macos-menubar-app/.

Before adding a file here, check whether it belongs in a docstring, an ADR,
a test, or a commit message instead. Status reports and dated handoffs go
stale in days and then actively mislead.
