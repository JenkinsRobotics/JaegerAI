# JaegerAI modules — independent folders per feature

Rule, 2026-10-22 rebuild: do NOT modify packages/jaeger-agent to improve it.
Improvements live here, as JaegerAI modules, and bolt on via the tool registry,
a host seam, or a Gateway adapter. Clean jaeger-agent stays clean.

Existing flat adapters in this folder (jaeger_agent.py, jaeger_kokoro_tts.py,
jaeger_whisper_stt.py) are unchanged. The folders below are new, one per feature,
created in the 2026-10-22 rebuild from the local jaeger-agent backup on the
Desktop (JaegerAI-jaeger-agent-local-2026-10-22/).

## Modules built in the rebuild

- team-handoff/ — call_agent + run_team, Gateway handoffs with approval, parallel specialists. Source: local call_agent.py, 14,592 bytes.
- safe-notes/ — locked, versioned specialist notes. Source: local agent_notes.py, 7,243 bytes.
- verified-messaging/ — send_message with verified receipt, never settle/retry an unknown send. Source: local messaging.py, 7,664 bytes. Depends on effect-ledger/.
- build-check/ — run_build_check, allowed build/test commands with JSON evidence. Source: local build_check.py, 5,423 bytes, JaegerAI-only.
- tool-executor-hardening/ — Hermes-style recovery, caller identity, goal confinement, owner approval. Source: local tool_executor.py, 25,284 bytes. Reference implementation for a host executor wrapper — do NOT drop it over clean jaeger-agent's tool_executor.py.
- workspace-project/ — project binding so tools run in the switched project. Source: local core/workspace.py, 26,456 bytes.
- effect-ledger/ — once-only ledger for authoritative actions. Source: local cognition/effects.py, 6,102 bytes.
- memory-runs/ — sqlite_runs + memory + sqlite_store refinements, preserved but not yet proven as a distinct feature. Check the line diff before wiring; drop this folder if no distinct feature is found.

## Client modules added 2026-10-22 — IDE + menu bar, registered, NOT duplicated

These two are thin clients, not jaeger-agent improvements. Their code already
lives in jaeger_ai/interfaces/, so these folders are stack registrations
(README + install/bolt-on + test plan), NOT second copies of the code.
Copying them here would create a second, drifting copy — do not do that.

- ide-client/ — Jaeger in your IDE. Registration for jaeger_ai/interfaces/ide/ (VS Code-compatible sidebar, extension.js 75,865 bytes). Build VSIX with package_extension.py, install from VSIX, no Marketplace. Loopback Gateway only; rejects non-loopback URLs. Remote IDE over Tailscale is NOT this module — that is ui-remote-access (WebUI + remote_access + Tailscale Serve).
- menubar-shell/ — Jaeger in the Mac menu bar. Registration for jaeger_ai/interfaces/macos-shell/ (Swift, StatusItemController, Hotkey, StackController, Voice). Menu bar status item, confirm-gated Start/Stop, loads UI via WebUI :8790, Gateway health :33418. Refactor of the old Swift menubar app; do NOT add the old app wholesale from Desktop archives.

## Personality + monolith break-out modules, added 2026-10-22

- personality/ — INCLUDED, not parked (correction 2026-10-22). Registration for jaeger_ai/features/personality/ (schema, character 29,178 bytes, compose, persona_state, 20 character folders). JaegerAI personality is the main version; jaeger-agent has NO personality file and NO character library (0 matches for "personality"), only prompts/persona_lane.py (38,384, Mode C routing), persona_filter.py, default_persona.py, and tools/persona.py (4,892, which IMPORTS JaegerAI personality — a host-seam issue, do NOT fix by editing jaeger-agent). Characters are persona packs for the ONE companion identity, not separate identities; default companion character still to confirm.
- gateway-server/ — split plan for core/gateway/server.py (388,486 bytes), by route group, thin router only. NOT yet cut — needs code-run + Gateway tests.
- main-cli/ — split plan for jaeger_ai/main.py (287,440 bytes, 6,303 lines), thin launcher only. NOT yet cut — check if still live CLI entry first.
- bridge/ — split plan for interfaces/bridge.py (220,695 bytes, 4,741 lines), transport/boot/turns/permissions, protocol v1 EXACT. NOT yet cut.
- gateway-session-store/ — split plan for core/gateway/session_store.py (143,703 bytes), records/transcripts/queries/archive, interface unchanged. NOT yet cut.
- tui/ — split plan for interfaces/tui/app.py (104,161) + slash_commands.py (104,769), by command group. Lowest risk, good first actual cut when code-run is available.
- entity-runtime/ — split plan for core/entity/runtime.py (57,253 bytes), prepare/execute/finish/status. Do NOT split verification.py (single-job safety).

Overlap rule, applied 2026-10-22: if JaegerAI and jaeger-agent overlap, keep the better version as the main module, keep the other as an OPTIONAL alternative only if it does a different job, otherwise move the worse version to Desktop. Corrected here: shared_memory (Honcho, optional shared memory) and dispatcher (primary/worker sessions + Kanban + sidecar 8646) and skill_tree (registry/seed/xp) are NOT straightforward duplicates of jaeger-agent memory/delegation/skills — they are JaegerAI alternatives / UI layers, so keep them as OPTIONAL modules pending an import check, do NOT delete them blind. No jaeger-agent file was edited in any of this work.

## Ai work audit modules, added 2026-10-22 — independent, NOT yet wired

Source folder: Desktop "Ai  work " (double space + trailing space, open via a trailing slash). Audited top level + all subfolders: JaegerAI_Archive (apps_ios, apps_swabble, skills, extensions, benchmark_results), JaegerAI (Aug 26 checkout, superseded), JaegerAI-Archive-20260908, Legacy-Review-2026-10-03, Old-Agent-Work, AgentStack, agent-tools, ares-* folders, 01_Screenshots, 02_ARES_Projects, 05_Documents, 07_Misc, 08_Config_Files, state-snapshots, terminals (251 transcript files), Mail Archive, loose plans/scripts.

- wake-word-swabble/ — Swabble, local-only Speech.framework wake-word gate, Swift 6.2, macOS 26, SwabbleKit, hooks, SRT transcribe. NOT in Jaeger repo before (0 matches). Registration only, upstream steipete/swabble, default wake "clawd" is NOT a Jaeger wake word — Matthew must pick one. Hook -> Gateway turn, approval gate still applies.
- ios-client-donor/ — Hermex / HermesMobile iOS 18+ SwiftUI client, DONOR REFERENCE ONLY, classified HISTORICAL/DONOR, targets Hermes WebUI, NOT Jaeger Gateway, NOT a qualified Jaeger phone client. Re-target to Gateway :33418 / WebUI :8790 + rebrand + license check before any code use. Includes Tailscale onboarding UX reference only.
- apple-mail-cleanup/ — ares-mail inbox_zero/junk_kill/bulk_junk + clean_inbox AppleScript, Apple Mail inbox-zero via osascript. DANGEROUS if wired wrong: deleting mail is irreversible, must be dry-run + report + approval bound to exact batch, NEVER list is personal and must be reviewed, not hardcoded.
- vault-queue/ — vault_queue.py copied verbatim (4,535 bytes, 139 lines, SQLite WAL job queue, stdlib only). The only Ai work code copied as code, because it is small/standalone. Optional alternative to dispatcher/work_ledger, not a duplicate. Test alone, then wire via tool registry.
- external-skills-catalog/ — skills_codex (31+ Claude Cowork + OpenAI curated/bundled/primary-runtime skill folders) + blockchain/gaming/social-media/yuanbao. CATALOG ONLY, do NOT copy wholesale (licenses unverified, bloat). Import ONE skill at a time, license-checked, Jenkins-first.
- project-boundaries/ — independence-plan.md principle (supersedes hive-mind-plan.md + hermes-autonomy-plan.md): boundaries by default, bridges by exception, single-writer ownership, updated to current Gateway :33418 / WebUI :8790. Also records the Paperclip answer (see below) and the Legacy-Review secrets warning.

Checked and NOT made into modules: agent-tools (43 UUID .txt transcripts, ~13MB, evidence not code), AgentStack (launch scripts + ~12MB logs, superseded by jaeger stack up), benchmark_results (Gemma/persona/everyday evals, old model evidence), JaegerAI Aug 26 checkout + archives (superseded by current repo), ARES folders + ares-* extensions (predecessor, not Jaeger stack), screenshots/documents/presentations/brand (media, not code), state-snapshots/terminals/test_init.db (state/transcripts), Mail Archive, 08_Config_Files/tailscale-ips.txt (config only). Paperclip: Legacy-Review README says Paperclip (agent-company manager) July trial, ~/.paperclip, 1.9GB, ~69 .env files, now paperclip-leftover/instances/ — separate trial product, NOT a Jaeger repo, NOT a module, SENSITIVE, do NOT import/share/sync. Legacy-Review total ~67GB with secrets by file name in its README — treat whole folder as sensitive, do NOT copy into JaegerAI. ARES-code there is noted as "only copy of uncommitted knowledge base + 5 modified files, port to Jaeger / commit before ever deleting" — preserve-before-delete flag, NOT an instruction to import ARES code now.

## Cleanup, 2026-10-22 — docs clean, junk out, code NOT cut

See docs/CLEANUP.md. Junk moved to Desktop/JaegerAI-removed-junk-2026-10-22/ (8 files, ~760KB): docs/PRODUCT.md, five NATIVE_*.md repair docs, MAC_APP_COMPLETION.md, BLUEPRINT_LEDGER.csv. Docs realigned to PRODUCT.md / STACK.md / TRUST.md, personality included, Swift link fixed to macos-shell. NO code files were moved, split, or edited in the cleanup, and NO git commit was run. What remains is IDE coding agent work only: build/test, wire modules one at a time, cut monoliths one group at a time, park non-stack features after an import check, resolve default companion + IDE host questions, then git commit.

## Status — read this before using them

These modules are EXTRACTED and preserved as independent folders, with a README
and a test plan in each folder. They are NOT yet wired into JaegerAI's runtime,
and NOT yet tested — the Mac app cannot run code or tests, and Mac control skips
Terminal. JaegerAI's runtime currently uses clean jaeger-agent (packages/jaeger-agent,
restored from standalone on 2026-10-22), so run_team, safe-notes, verified-messaging,
and build-check are NOT available in the runtime until they are wired in and tested
with an agent that can run code.

Wiring steps, in order, when code-run is available: one module at a time, test alone,
then test bolted on, starting with build-check (simplest), then safe-notes,
verified-messaging, team-handoff, then the executor / workspace / ledger wrappers.
Do not wire all eight at once.

## Backup and restore, 2026-10-22

- Local jaeger-agent backup (pre-rebuild, full local copy): Desktop/JaegerAI-jaeger-agent-local-2026-10-22/
- Old packages/jaeger-agent folder also trashed recoverably: /Users/matthewjenkins/.Trash/jaeger-agent
- Restored packages/jaeger-agent: source only from standalone /Users/matthewjenkins/GitHub/jaeger-agent (LICENSE, README, pyproject, MANIFEST, VERSION, docs/, jaeger_agent/, scripts/, tests/). Build artefacts benchmark_results/ and jaeger_agent.egg-info/ were NOT restored, on purpose — they are not source.
- Standalone jaeger-agent repo itself was NOT edited. Only JaegerAI's inside copy was restored.
