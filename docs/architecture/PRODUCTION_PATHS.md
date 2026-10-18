> **Classification:** CURRENT AUTHORITATIVE (canonical runtime path).
> **Enforced by:** `dev/tests/jaeger_ai/contract/test_single_path_architecture.py` — every claim
> below marked *(test)* fails that file if it stops being true.

# Production paths: one Gateway

The Gateway (`jaeger gateway daemon`, `:8810`) is the single production runtime. A Jaeger turn has
one path. Everything else is a client of it, an adapter into it, a library it calls, or is
isolated behind `JAEGER_LEGACY_PATHS` (`jaeger_ai/contract/legacy_paths.py`).

## The one path

```
client  WebUI · IDE · menu bar · TUI · CLI · voice · MCP/A2A · bridge faces
  │      (each presents its own caller token; the Gateway binds the actor)
  ▼
Gateway  POST /v1/sessions/{id}/turns            core/gateway/server.py
  │      admit: durable request receipt + frozen execution snapshot
  ▼
classify conversation | work                     is_actionable_request + ExecutiveStrategySelector
  ├─ conversation → resident Entity turn, no task, presence: listening → thinking → done
  └─ work → ONE Goal/TaskCard on GatewayTaskOwner, same session
        │   plan      ExecutiveStrategySelector decision (strategy, complexity) → `planning`
        │   policy    PolicyKernel judges every tool call as the admitting caller
        │   worker    EntityRuntime.run_subordinate_react, durable mode, EVIDENCE_CONTRACT
        │   evidence  work-ledger file receipts (sha256) or artifacts declared at admission
        │   verifier  GatewayTaskOwner.verify — re-hashes the file; changed/missing ⇒ not verified
        ▼   settle    tasks.completion.authoritative_transition — the only completion writer
     completed_verified | needs_owner | blocked | failed | cancelled   (paused: outcome unknown)
        │   events    GatewayEventBus: jaeger.state · task.created · task.updated · turn.*
        ▼   receipt   in the turn result and on the stream, in the same conversation
```

A worker returns evidence. It does not choose a state. A bare `ok`, `success`, `done`, an empty
result, a forged `completed_verified`, a count-only ledger, or a receipt for a file that has
since changed all settle as `failed` *(test)*. An owner-declined approval settles as `blocked`.

## One owner per fact

| Fact | Authority | The only writer | Everything else |
|---|---|---|---|
| Conversations, requests, attachments | `GatewaySessionStore` | itself | clients read over REST/SSE |
| Tasks, goals, task history | `GatewayTaskOwner` + `SqliteDurableTaskStore` *(test)* | `GatewayTaskOwner` | workers return evidence |
| Task state `completed_verified` | `tasks/completion.py::authoritative_transition` *(test)* | called only by the owner | no other module names or assigns it |
| Event stream and presence | `GatewayEventBus` *(test)* | `GatewayEventBus` | WebUI/IDE/menu bar/avatar/phone project it |
| Identity | `EntityIdentity` (`entity_identity.json`) *(test)* | `identity.rename_entity` | `identity.yaml` is a projection; setup/settings are config inputs |
| Experience (episodic) | `SqliteEventStore` | `EntityRuntime` | |
| World claims (observed / inferred / planned / verified) | `WorldClaim` in `SqliteWorldStore` | `EntityRuntime.record_world_claim` | Gateway and owner ask it to |
| Agent facts (preferences, corrections) | `SqliteMemoryStore` | memory tools in the resident Entity | PolicyKernel denies them to outside callers *(test)* |
| Model routing | `core/models/router.py` | the router's decision | Gateway direct lanes use it; private text stays local |
| Side effects | `SqliteRunStore` effect ledger | `EntityRuntime` | |

## Every path found, and what it is

**Canonical.** `Gateway._execute_turn` → `EntityRuntime.run_subordinate_react` (owner ReAct).
`GatewayTaskOwner`, `GatewayEventBus`, `PolicyKernel`, `EntityIdentity`, `MemorySubsystem`.

**Adapter into the Gateway.** WebUI (`webui_chat_backend_mode` = gateway); IDE extension;
Swift app (REST + SSE); bridge native op **and attach op** (`_gateway_turn`); TUI
(`GatewayTurnClient`); CLI one-shot (`_forward_oneshot_to_gateway`); `jaeger voice`
(`features/voice`); MCP and A2A servers (their own caller tokens); background producers (the
Gateway's sink); IDE orchestration (dispatch transport — every admission opens a card on the
task owner *(test)*; its worker `completed` is a transport status, shown as `state` next to the
owner's `task_state`).

**Library used by the Gateway.** `jaeger_agent` loop and tools; `core/models/router.py`; work
ledger; `ExecutiveStrategySelector`; verification registry; delegates (codex/claude/gemini
subprocess workers, cancelled by process tree, `unconfirmed` when a descendant survives).

**Isolated — disconnected from production, not deleted (`JAEGER_LEGACY_PATHS=1` re-enables).**

| Path | How it is disconnected |
|---|---|
| `run_for_voice`, `_run_turn`, the in-process runtime and interactive loop in `main.py`, `run_command`, the fact-review writer | `require_legacy_path` at entry *(test)*; a CLI one-shot is forwarded to the Gateway first *(test)* |
| Bridge local execution (`JAEGER_BRIDGE_EXECUTION=local`, `_boot_agent`) | `local` alone is ignored; needs the legacy switch *(test)* |
| `plugins/voice_loop.py`, `plugins/messaging_daemon.py`, the PySide6 shell | reach only the guarded turn functions; `--voice` routes to `jaeger voice` |
| `EntityRuntime.execute_turn` (full UPAA pipeline: executive → router → verification → learning) | callable only from the guarded `main.py` path and the fault injector *(test)* |
| Gateway native-MCP lead lane | behind `legacy_paths_enabled()` *(test)* |
| WebUI in-process agent, `:8791` runner, Hermes/OpenClaw/Roundtable profiles | existing switch |
| Deep Think daemon | `run_daemon` now runs the Gateway owner; legacy board cards are imported once into `GatewayTaskOwner` (`migrate_legacy`) and the board is a projection |

**Deleted in architecture cleanup.** `jaeger_ai/mind/cognition/` (3,027 lines: duplicate identity,
planner, router, orchestrator, evaluator, trust engine, worker registry superseded by `core/entity/`) and
`jaeger_ai/interfaces/messaging/` (Slack Socket Mode folded into `features/channels/platforms/slack.py`)
have been completely removed; pinned forbidden *(test)* so they never reappear.

## Avatar, phone, Minecraft

An avatar or phone reads `jaeger.state` (`contract/presence.py`, `project_presence`). It owns no
memory, identity, goal, permission or task state: its package imports none of the authorities
*(test)*. Minecraft is not an agent: the tool module opens no socket and runs no loop, PolicyKernel
denies `mc_*`, and `EmbodimentGate` refuses *(test)*. It stays disabled.

## Not consolidated yet

- **DeliberatePlanner and the UPAA verification pipeline are not in the Gateway lane.** The Gateway
  plans with the executive's decision plus the work ledger; the LATS-style `DeliberatePlanner` runs
  only inside `execute_turn`.
- **Two semantic stores.** Agent facts (`memory.sqlite3`) and world claims (`knowledge.sqlite3`)
  are separate by category. Ownership is single and enforced; the physical stores are not merged.
- **A worker's text answer has no objective evidence.** Evidence is a file receipt. Work whose
  result is only prose settles `failed` (unverified) until a deliverable is declared.
- **Messaging (Telegram/Discord/iMessage) has no Gateway adapter.** The wired daemon is isolated;
  it needs a caller identity of its own before it can be reattached.
- **Request ids are global, not per session.** An identical retry replays the first receipt even from
  another session. It returns only the response to text the caller already sent, but ids should be
  scoped to a session.
- Delegate-health telemetry shares the memory SQLite file (`delegates/health/store.py`); it is not
  owner memory.
