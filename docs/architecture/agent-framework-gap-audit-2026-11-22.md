# Agent framework gap audit — 2026-11-22

## Scope and method

This audit compares JaegerAI with the installed Codex/ChatGPT desktop app,
the installed Grok Bot app, Hermes Agent, the official open-source Codex
repository, and the agent-framework repositories already present beside
JaegerAI. Proprietary applications were inspected as behavior and architecture
evidence only. No proprietary or vendor source was copied into JaegerAI.

The local JaegerAI `master` branch was reconciled with `origin/master` without
discarding the two pre-existing local commits. Hermes Agent and official Codex
were refreshed to their remote default branches. The incomplete AutoGPT Git
directory was repaired with a shallow checkout of its remote `master`.

## Component-by-component findings

### Installed Codex/ChatGPT desktop

- Installed artifact: `/Applications/ChatGPT.app`, bundle
  `com.openai.codex`, version `26.1106.51428` (build `26605`).
- ASAR SHA-256:
  `3695c17edcab8d66c1e5f2faa03e07826a59a39bf78b369ec87854547d4843c1`.
- REA inventory evidence:
  `ev_6c37b63d3ddf68036c33b67941293278ebd48b11a9660e41f6d89f66a9e38a71`.
- Focused JavaScript evidence:
  `ev_1bb0c0ae8afc0d68c24a8b8a033bab63431b95f83eb997d69b696b4989c25b87`.
- Observed architecture: narrow Electron context bridges, chunked IPC with
  acknowledgement, a dedicated Git worker, browser/design annotations, MCP
  sandbox guest ports, and WebMCP discovery/execution.
- Already in Jaeger: Gateway-owned turn queue and steering, durable receipts,
  session recovery, Git/file tooling, shared browser, approvals, and tool
  confinement.
- Reusable gap: page-native WebMCP tools were not exposed through Jaeger's
  shared browser. This audit implements that gap.
- Not copied: Electron IPC layout, proprietary bundles, private MCP sandbox
  protocol, and app-specific design-editor implementation.
- Limitation: seven packaged native-file integrity records contradicted their
  declared hashes. Those nodes were recorded as untrusted and were not used as
  implementation evidence. Findings are static, not live runtime acceptance.

### Installed Grok Bot

- Installed artifact: `/Applications/Grok Bot.app`, bundle
  `com.anysphere.sand`, version/build `1.1.0`.
- ASAR SHA-256:
  `2ce3b335f3d92c7be6ad59da397f8f6bf16c6d29474041ec5cc1e508b65b8e48`.
- REA inventory evidence:
  `ev_df41454a8a04eb0d9f5c4af620eb45b1163f0bebe690e2d2331621640ac05121`.
- Focused JavaScript evidence:
  `ev_174d951d63ca383d6f060f9e403a542d03d9a77882a26a2cc281fb316140d739`.
- Observed architecture: main-agent/secondary voice-call relay, durable
  per-call JSON journal, checkpoint heartbeats, connectors, schedules,
  notifications, meetings, and voice-call surfaces.
- Already in Jaeger: voice and device surfaces, channels, schedules, durable
  task/checkpoint state, notifications, memory, and specialist delegation.
- Decision: do not add Grok Bot's vendor services or a competing journal,
  scheduler, relay, or runtime. Jaeger's existing Gateway ownership covers the
  transferable behavior.
- Limitation: twelve integrity contradictions were recorded as untrusted and a
  large main bundle reached the analyzer's call-stack limit. Findings are
  partial static evidence.

### Hermes Agent

- Local checkout: `0f602c5f6f18615632535251d62a2db74ce93b69`, clean and equal
  to `origin/main` when audited.
- Transferable patterns: tool-call recovery, checkpointing, delegated-worker
  suppression boundaries, skills, and persistent agent behavior.
- Already in Jaeger: Hermes-derived executor recovery is explicitly present in
  `packages/jaeger-agent/jaeger_agent/tool_executor.py`; Jaeger also has durable
  runs/checkpoints, skill loading, child grants, and specialists.
- Decision: retain the existing integrations; no second loop, Gateway,
  checkpoint store, or delegation owner was added.

### Official OpenAI Codex

- Local checkout: `ae6c0c8ac164bdead234d8cdc794dbcdc5b37d28`, clean and equal to
  `origin/main` when audited.
- This is the official Apache-2.0 Codex repository, not a claim that the
  proprietary desktop application is open source.
- Transferable patterns: resumable conversations, sandboxed execution,
  approval-aware tools, TUI interaction, and replay-safe event handling.
- Already in Jaeger: Gateway-owned queued work, mid-turn steering, recovery,
  sandbox/permission policy, approval cards, effect receipts, and persisted
  turn parts.
- Decision: use the official source as a reference and the installed app as
  clean-room behavioral evidence; do not create a Codex-compatible competing
  runtime.

### Other local framework repositories

| Framework | Audited revision | Distinct emphasis | Jaeger decision |
| --- | --- | --- | --- |
| AutoGPT | `dd0b5f73266e` | visual workflow/platform automation | Checkout repaired; workflows already use Jaeger's durable Task owner |
| MetaGPT | `11cdf466d042` | role-based software teams | covered by specialists/team/handoffs |
| OpenHands | `c5e47c4b4dab` | coding workspace and automations | covered by workspace tools, browser, tasks, and approvals |
| AG2 | `db7194e8e267` | conversational multi-agent orchestration | covered by canonical specialist path |
| Agno | `e59ca576219e` | teams, services, durable workflows | covered by Gateway, tasks, workflows, and team registry |
| Cline | `8075d2e35cf5` | IDE coding agent | covered by Jaeger IDE and Gateway-backed tools |
| CrewAI | `56c26a7fb3ec` | crew/flow orchestration | covered by teams plus durable workflows |
| Gemini CLI | `eecccfcd5aff` | terminal coding and session resume | covered by CLI/IDE surfaces and persisted sessions |
| Goose | `4dcfe297beed` | extensible local coding agent | covered by skills, MCP, tools, and permission tiers |
| LangGraph | `c6335a4255dc` | graph durability and interrupts | covered by Task owner, checkpoints, queue, and approvals |
| OpenCode | `bab0d0413ff3` | terminal/desktop coding agent | covered by Jaeger client surfaces and coding tools |
| Pydantic AI | `463a6d519b7e` | typed agents, durable execution, sandboxes | covered by schemas, durable runs, and sandbox policy |
| smolagents | `99721bdc3b6f` | compact code agents and sandboxes | covered by agent loop, tool registry, and sandbox policy |

This is a capability comparison, not a claim that every repository has been
fully ported or that repository-level tests prove live Jaeger behavior.

## Implemented gap: WebMCP in the shared browser

Jaeger's existing Gateway-owned browser now supports two additive actions:

- `webmcp-tools`: feature-detect and list at most 100 same-origin page tools.
- `webmcp-call`: refresh the page's current tools and invoke exactly one
  exact-name match with a JSON-object input.

The implementation uses the current `document.modelContext.getTools()` and
`executeTool()` API. It enables Chromium's `WebMCP` feature flag, fails closed
on missing or duplicate tool names, does not accept model-supplied session
identity, and labels page descriptors/results as untrusted content. Existing
`EXTERNAL_EFFECT` approval policy, session admission, Gateway authentication,
global Stop, effect ledger, and browser ownership remain authoritative.

Changed surfaces:

- `packages/jaeger-browser/worker.mjs`
- `jaeger_ai/features/browser/runtime.py`
- `jaeger_ai/features/browser/routes.py`
- `packages/jaeger-agent/jaeger_agent/tools/browser.py`
- `packages/jaeger-agent/jaeger_agent/tools/browser_shared.py`
- `packages/jaeger-browser/README.md`
- `dev/tests/jaeger_ai/features/test_browser_workspace.py`

## Verification

- `node --check packages/jaeger-browser/worker.mjs` — passed.
- `git diff --check` — passed.
- `./dev/scripts/run_tests.sh --unit dev/tests/jaeger_ai/features/test_browser_workspace.py`
  — 5 passed, 1 skipped. The skipped test requires an explicitly built browser
  bundle. The first sandboxed run could not bind its local aiohttp test socket;
  the identical suite passed outside that network sandbox.

No live Jaeger runtime acceptance is claimed: the user requested the current
agent be stopped, so the stopped Gateway stack was not restarted merely to
exercise this change.
