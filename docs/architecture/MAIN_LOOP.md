> **Classification:** CURRENT AUTHORITATIVE.
> **Current execution entry point:** [`docs/CONTINUE_FROM_HERE.md`](../CONTINUE_FROM_HERE.md)

# The main loop

One path runs every Jaeger turn. Everything else plugs into it; nothing else executes a turn.

```
client (IDE / WebUI / TUI / Mac app)
   │  POST /v1/sessions/{id}/turns          (workspace, model, options.ide)
   ▼
Gateway  jaeger_ai/core/gateway/server.py
   │  admit_request        → immutable execution snapshot, idempotent by request_id
   │  _execute_turn
   │     1. runtime.prepare_turn      memory READ: history, other conversations,
   │                                  learned skills, retrieved docs, reflexion,
   │                                  runtime truth, IDE context   → one fenced prompt
   │     2. _sync_react               the agent loop (or a model-only lane, below)
   │     3. runtime.finish_turn       memory WRITE: answer → event + episodic record
   │  complete_request     → messages, activity, SSE events
   ▼
agent loop  packages/jaeger-agent/jaeger_agent/loop/jaeger_agent.py
   model call → tool calls → tool results → … → answer      (streams to the client)
```

Chat turns and durable background tasks take exactly this path. There is no second turn
shape.

## What a turn is

`EntityRuntime.prepare_turn` (`jaeger_ai/core/entity/runtime.py`) builds the request. The
context blocks are JSON-fenced as read-only *data* by `cognition_router.with_background`,
so recalled text or selected code is never read as an instruction. Every block is
best-effort: if memory is unavailable the operator's request still reaches the agent
unadorned.

`EntityRuntime.finish_turn` records the answer as an `agent.response` event and an episodic
memory, which is what later turns, in any conversation, recall.

## Lanes in front of the loop

Two session-level choices bypass the tool loop on purpose, at the Gateway boundary:

| Lane | When | Why |
|---|---|---|
| image question | attached image and a question about it | goes straight to a vision model |
| model-only | text-only conversation, or an agent registered as a specialist | a plain answer, no tools |

## Extension points (how everything else connects)

| To add | Plug in at |
|---|---|
| a capability | a tool: `@register_tool_from_function` in `packages/jaeger-agent/jaeger_agent/tools/`, classified in `skill_registry/toolset_scoping.py` |
| know-how | a skill folder under `packages/jaeger-agent/jaeger_agent/skills/` (`SKILL.md`); found automatically |
| context the model should have | a block in `prepare_turn` (fenced by `with_background`) |
| work that runs later or in the background | a durable task: `GatewayTaskOwner.submit` (`jaeger_ai/core/tasks/owner.py`); agent code reaches it through `jaeger_agent/task_port.py` |
| something that watches or reacts | a background producer (`jaeger_ai/core/runtime/background_producers.py`), which submits tasks |
| a client | speak REST + SSE to the Gateway; never execute a turn locally |

## Permissions

`automation.autonomy` in the instance `config.yaml` (default `auto`): no approval prompts on
the operator's own machine. `scoped` prompts once per new kind of action; `ask` prompts every
time. Catastrophic commands (`rm -rf /`, disk wipes) are refused below every mode by
`hardline_guard`, and every action is audited (`logs/audit.log`).

## Isolated, not deleted

Earlier execution paths remain in the tree behind one switch, `JAEGER_LEGACY_PATHS=1`
(`jaeger_ai/contract/legacy_paths.py`): the WebUI's in-process agent and profile runners, the
Gateway's native-MCP-first lead turn. They are off by default and fail closed with an explicit
error. The salience gate, executive strategy selection, cognition router, verification pass
and self-refine critic (`EntityRuntime.execute_turn`) also stay in the tree, off the turn
path, as material for the autonomy lane.

## What the WebUI shows

The WebUI is a client of the Gateway like the IDE: its sidebar is a mirror of the Gateway's
conversations (`features/webui/api/gateway_mirror.py`), and chat goes through `/v1/sessions`.
Only the tabs that work with Jaeger are shown: **Chat, Spaces, Settings**. The rest read the
legacy Hermes systems and show empty or wrong data, so they are hidden, not deleted
(`HIDDEN_WEBUI_TABS` in `contract/legacy_paths.py`, enforced by the server and applied at page
load). Only the `jaeger` profile is offered. `JAEGER_LEGACY_PATHS=1` shows everything again.
Imported Claude Code / Codex history is off by default (a Settings toggle).

## Flags that change the path

| Flag | Effect |
|---|---|
| `JAEGER_LEGACY_PATHS` | re-enables the isolated legacy paths |
| `JAEGER_OWNER_REACT` | forces the resident agent loop in the legacy native-MCP branch |
| `JAEGER_TOOLSET_SCOPING` / `JAEGER_FULL_TOOLS` | narrow / widen the tool schema the model sees |
| `automation.autonomy` (config) | approval behaviour, above |

## Proof it works

`dev/scripts/gateway_turn.py` drives one real turn through a Gateway the way the IDE does;
`dev/benchmark/gateway_battery.py` runs coding tasks end to end and grades each with an
independent verifier (never the model's own claim). Run them against a scratch Gateway on
another port with a scratch `JAEGER_STATE_DIR`, never the operator's live one.
