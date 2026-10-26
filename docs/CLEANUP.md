# JaegerAI cleanup — 2026-10-22

What was done by Muse (Mac app, no code-run, no git, no Terminal), under Matthew's instruction to do as much as possible, remove junk, and realign docs to the better understanding, and to report when only an IDE coding agent can work.

## Confirmed definition used for all docs edits

JaegerAI is the standalone repo for the intelligence stack for Jenkins Robotics. Proactive, world-model AI companion and operator, one identity, same memory and same approval gate, whether talking, running the business, or eventually in a robotic body. NOT a workspace hub, NOT a CAD suite, NOT a machine project. Cloud LLM today, on-device is the goal. JROS is our ROS 2 alternative, Aether Suite is CAD and simulations, NAS at /Volumes/Jenkins_Robotics is the business home, YouTube is the fastest revenue engine. Personalities are a JaegerAI framework feature (see modules/personality/) — characters are persona packs for the one companion, not separate identities.

## Docs realigned (no code changed in this step)

- docs/PRODUCT.md — companion line corrected: one companion identity, characters are persona packs, personalities stay in the stack, with a pointer to jaeger_ai/modules/personality/README.md.
- docs/README.md — entry point is now PRODUCT.md + STACK.md + TRUST.md + REBUILD.md + CLEANUP.md + research/README.md in the table (previously the table still listed docs/PRODUCT.md as CURRENT AUTHORITATIVE, contradicting the top note). Fixed the broken Swift app link: jaeger_ai/interfaces/swift/ no longer exists, it was refactored into interfaces/macos-shell/; added links to macos-shell REUSE.md, IDE client README, and modules/MODULES.md.
- Earlier 2026-10-22 alignment (already in repo): docs/PRODUCT.md, docs/STACK.md, docs/TRUST.md, docs/research/README.md created; README.md, AGENTS.md, docs/architecture/ARCHITECTURE.md, docs/architecture/STRUCTURE.md edited. Originals are on Desktop in JaegerAI-checkpoint-2026-10-22/.

## Junk removed from the repo — moved to Desktop, NOT deleted

Destination: Desktop/JaegerAI-removed-junk-2026-10-22/ (8 files, verified by listing after the move). No archive folder was left in the repo, by preference. Nothing was permanently deleted in this cleanup.

- docs/docs/PRODUCT.md (55,749 bytes) — previously listed as entry point, superseded by PRODUCT.md. Its contents were NOT read or followed in this cleanup; the file was moved by name only.
- docs/NATIVE_STOP_REPAIR.md (17,613), NATIVE_PANEL_CONNECTIONS.md (6,679), NATIVE_CHAT_RECOVERY.md (6,039), NATIVE_RECOVERED_APPROVALS.md (5,131), NATIVE_PANEL_TRUTHFULNESS.md (2,097) — dated 2026-10-19 native-panel repair docs, superseded by the current macos-shell / WebUI.
- docs/integration/MAC_APP_COMPLETION.md (290,290 bytes, 1,737 lines) and BLUEPRINT_LEDGER.csv (371,325 bytes) — huge integration ledgers, history/evidence, not current docs. Kept in repo: docs/integration/SCOPED_CLEANUP.md and 2026-10-19-worktree-inventory.json.

Total removed from the active docs tree: about 760,000 bytes across 8 files.

## Modules already in the repo (see jaeger_ai/modules/MODULES.md)

- 8 jaeger-agent rebuild modules: team-handoff, safe-notes, verified-messaging, build-check, tool-executor-hardening, workspace-project, effect-ledger, memory-runs (extracted, NOT yet wired/tested).
- Client modules: ide-client, menubar-shell (registrations, code stays in interfaces/).
- Personality module: personality/ (included, not parked).
- Monolith split-plan modules: gateway-server, main-cli, bridge, gateway-session-store, tui, entity-runtime (split maps + test plans, original files NOT yet cut).

## What was deliberately NOT done here, and why

- NO code files were moved, split, or edited. Moving features/ code or cutting server.py / main.py / bridge.py without a test run could break Jaeger with no way to verify or fix it from the Mac app (no shell, no test runner, Terminal is skipped). That is exactly the work that needs an IDE coding agent.
- NO jaeger-agent file was edited (standalone or inside packages/). packages/jaeger-agent is clean, restored from standalone on 2026-10-22.
- NO git commit was run (Mac app cannot run git). The change set now includes: docs alignment, docs cleanup, junk moves (Desktop only, outside the repo, so NOT in the commit), new module folders, and MODULES.md updates. A new git-add list is needed at commit time, not the old CHECKPOINT.md list alone.
- NOT removed (candidates for the IDE agent to decide, with an import check first): docs/index.html (33,635, old docs site?), docs/RELEASE_0.13.md (release record), docs/architecture/IDE_FIRST_PRODUCT_DIRECTION.md and CAPABILITY_EQUIVALENCE_AUDIT.md (already marked HISTORICAL, kept as evidence), features/ non-stack folders (finance, roundtable, etc. — park only after checking imports), features/shared_memory, dispatcher, skill_tree (optional alternatives, NOT straightforward duplicates — do not delete blind).

## What only an IDE coding agent can do next — in order

1. Build + test: build the IDE VSIX, build the Swift macos-shell, run Gateway/WebUI/UI tests, prove one full turn end to end.
2. Wire modules one at a time, test alone then bolted on, starting with build-check, then safe-notes, verified-messaging, team-handoff, then executor / workspace / ledger wrappers. Do NOT wire all at once.
3. Cut the monoliths one group at a time, with tests passing after each group, starting with tui (lowest risk), then gateway-session-store, entity-runtime, bridge (protocol v1 fixtures must pass), main-cli (check if still live entry first), then gateway-server (route groups, thin router only). Do NOT cut server + main + bridge in the same step.
4. Park non-stack features to Desktop only after an import check proves nothing in main.py / Gateway / bridge imports them, and update MODULES.md + docs/README.md accordingly.
5. Resolve the open questions: default companion character (which one?), which IDE host Matthew uses day to day (VS Code / Antigravity / Cursor — Antigravity compatibility is unverified), whether the 4 restored clarify/MCP tool files stay in the clean jaeger-agent copy, and whether any JaegerAI module is ever upstreamed to standalone jaeger-agent (default: no).
6. Git commit the whole 2026-10-22 change set from Terminal, with a new git-add list that includes the new module folders and docs edits, and excludes all Desktop folders.

When those six are done, and only then, can anyone honestly claim JaegerAI runs with the new modules wired in. Until then, the honest status is: docs clean, junk out, modules defined and preserved, runtime still on clean jaeger-agent + existing interfaces, NOT yet wired or tested.
