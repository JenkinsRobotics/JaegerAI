# JaegerAI Execution Authority Audit

**Phase:** 2 — execution authority, task completion, and delegation
**Date:** 2026-09-15
**Checkout:** `main` at `612d6ee3afb1e4f2e59b83d831eddb35d43af1df`
**Baseline:** [RUNTIME_TRUTH_AUDIT.md](RUNTIME_TRUTH_AUDIT.md)
**Scope:** forensic audit only. No production behavior, dependencies, legacy code, or architecture was changed. This report is the only repository file created/updated for Phase 2.

## Executive finding

Jaeger has two different completion regimes:

1. **Interactive chat:** `jaeger_ai.main` → `JaegerAgent` → `drive_one_turn`. This is a bounded conversational ReAct/tool loop. It can perform multiple sequential tools, but a final model message is normally enough to end the turn. It does not, by itself, own a durable objective, independent repository verification, or a long-lived job.
2. **Autonomous and subagent work:** `JaegerAgentController` wraps repeated inner turns and uses a `WorkLedger`/`complete_task` gate. The gate requires countable work to be finished and attached verification to pass before the controller reports completion. This is the closest existing execution authority.

The controller is **PARTIALLY** the missing “work until complete” authority. It is not the authority for every actionable request: ordinary chat and Gateway text-only requests can terminate outside it; external delegates and native Hermes/OpenClaw Runs own their own execution state; and delegate results are not automatically followed by Jaeger-side filesystem/test verification. Therefore the audit conclusion is:

> **NO SINGLE COMPLETION AUTHORITY PROVEN** for all Jaeger requests.

## Phase 1 baseline recheck

The Phase 1 findings still hold at this checkout:

* `jaeger_ai.main` is the product façade and ordinary turn host.
* `JaegerAgent` and `drive_one_turn` own the ordinary inner loop.
* `JaegerAgentController` exists as an outer autonomous/job state machine.
* `jaeger_agent.delegates` is a separate lifecycle port and registry.
* `core/frameworks/backends.py` is a separate native Runs registration table.
* Gateway has a lead MCP path and specialist/text-only Ollama path.
* Hermes and OpenClaw can be external/native execution services.
* JaegerOS `ToolDef`, the composed executor, checkpoints, and `EffectLedger` exist.

The worktree remains dirty with extensive user changes and untracked files; it was not reset or cleaned. The Swift product build now passes, but the configured local model still fails the doctor probe as recorded in Phase 1.

## Terms and lifecycle semantics

| Term | Primary representation | Created by / owned by | Persistence and terminal semantics | Retry/cancel/verification |
|---|---|---|---|---|
| **Turn** | `JaegerAgent.run_turn`; Gateway `client_requests` | Client (`main`, bridge, Gateway) / inner agent | Transcript and Gateway request/event rows may persist; ends on final text, halt, error, or interrupt | Inner loop retries truncation/context cases; cancellation interrupts; no objective verification by default |
| **Task** | `WorkLedger` plus `work_ledger`/`complete_task` tools | Autonomous prompt/agent / work-ledger module | Ledger persists under operator state; `RUNNING` → `COMPLETED` only through `complete_task` | Refuses incomplete counts or failed attached verification; continuation retries by spending steps; stop fails |
| **Job** | `JaegerAgentController` (`AgentState`) | `run_autonomous`, `run_worker_goal`, autonomous runner | Controller state is in memory; underlying execution state/ledger can persist | Budget, stop, blocker, and error handling; repeated turns; no restart-safe controller object itself |
| **Run** | `jaeger_agent.cognition.runs.Run` / SQLite run store; native `Runs.Run` | DelegateExecutor or native backend adapter | Durable Jaeger run store has `created/active/waiting_for_event/completed/blocked/failed/cancelled`; native Runs writes JSON journals | Checkpoints, heartbeat, recover/resume for cognition runs; native backends reconcile/cancel with `execution_unknown` handling |
| **Session** | Gateway session row; bridge session key; MCP session | Gateway/client protocol | Gateway messages/events persist; MCP/bridge session state is transport/runtime scoped | Request busy/cancel/SSE; not itself an objective verifier |
| **Subagent** | Fresh `JaegerAgent` in `core/runtime/subagents.py`; optional controller | `delegate_task` tool | Parent receives a result payload; optional git worktree is temporary and finalized | Depth-limited; isolated context/worktree; batch child uses controller; parent does not automatically run independent tests |
| **Delegate** | `DelegateRequest`, `DelegateHandle`, `DelegateResult`, runtime registry | CLI/Gateway handoff/subagent code | Delegate execution is mirrored into a Jaeger `Run`; external runtime may own additional state | Probe, start, stream, result, cancel, one-shot resume generally unsupported; failover can retry another delegate |
| **Worker** | `run_worker_goal` / subprocess invocation | Autonomous child or external delegate | Child output/events and run checkpoints may persist; process lifetime is bounded | Controller budget/stop; subprocess timeout kills process; cleanup is best effort |
| **Effect** | `EffectLedger` / `Effect` and `SqliteEffectLedger` | Tool executor at dispatch | Effect claim/result is durable when ledger is bound; indeterminate effects are fail-closed | `once()` prevents duplicate authoritative external effects; this is idempotency, not task correctness |
| **Tool call** | `ToolDef.dispatch` through executor wrappers | Model decision, then `JaegerAgent` | Message/tool result recorded in turn; side-effect claim may be ledger-backed | Argument validation, allowlist, hooks, checkpoint, effect dedupe; no universal objective verifier |

These are not all duplicates. `Run` is an execution-attempt lineage object; `Job` is a controller loop; `WorkLedger` is an objective/progress/completion gate; Gateway request rows are transport durability; native Runs journals are adapter-facing receipts.

## Case A — ordinary conversation

For “What is the capital of Egypt?” the normal local path is:

```text
User
  -> cli.entry / bridge / TUI
  -> jaeger_ai.main._run_turn
  -> build/reuse JaegerAgent
  -> drive_one_turn
  -> model adapter (local GGUF/MLX or configured external provider)
  -> no tool call, or ToolDef executor if selected
  -> final assistant text
  -> run_command / bridge reply / UI event
```

The inner loop stops when the model returns final text, hits a turn/tool/iteration/context guard, is interrupted, or raises. “Success” here means a returned conversational result, not proof of an external objective.

Gateway chat has a parallel form:

```text
POST /v1/sessions/{id}/turns
  -> Gateway admission + request row
  -> lead: MCP chat tool at :8811, or specialist/text_only: Ollama /api/chat
  -> persist result + SSE terminal event
```

The Gateway route is deliberately selected from session role and `execution_mode`. The specialist/text-only branch is model-only: it has no JaegerOS tool registry, effect ledger, delegate choice, or subagent controller in that request. If an action-capable request is marked specialist/text_only, the route can return prose without executing the requested work. This is a material P1/P2 routing risk.

## Case B — repository work request

The intended action-capable local path is:

```text
User objective
  -> main detects batch/autonomous shape
  -> WorkLedger created/injected
  -> JaegerAgentController [J]
       -> JaegerAgent/drive_one_turn [T]
            -> JaegerOS tools [E]
            -> optional delegate_task
                 -> fresh JaegerAgent (+ controller for batch child)
                 -> optional isolated git worktree
            -> continuation / verification prompt
       -> complete_task requires ledger counts + attached verification
  -> controller terminal result
  -> parent summary / progress event
```

The controller owns objective continuation, step budget, stop handling, blocker classification, and the final `complete_task` observation. `WorkLedger._run_verification` checks declared paths and receipts, not arbitrary semantic correctness. A test command is only proven if the model/tool actually records it or a verifier attached to the ledger checks it.

For external delegate execution, the path is different:

```text
Jaeger/Gateway/CLI
  -> DelegateRequest + DelegateExecutor [D, P]
  -> runtime.probe()
  -> runtime.start(workspace, prompt)
  -> streamed DelegateEvent checkpoints
  -> runtime.result() => DelegateResult
  -> Jaeger Run terminal state
```

The delegate result is evidence available to the caller. It is not, by contract, completion authority: `DelegateResult` explicitly says delegate output is evidence, never authority. In the inspected callers, there is no universal post-result Jaeger action that inspects the workspace, runs tests, and independently proves the objective.

### Responsibility answers for Case B

| Responsibility | Current owner | Proven? |
|---|---|---|
| Hold objective | WorkLedger/controller when autonomous mode is entered | Yes for that mode; no for ordinary chat/delegate CLI |
| Decide incompleteness | Ledger counts, attached verification, controller continuation | Yes for ledger-backed workers |
| Choose tools | Model plus Jaeger tool catalog/allowlist | Yes for native/subagent Jaeger |
| Choose delegates | Delegate router/caller; model can invoke `delegate_task` | Yes, but not universal |
| Receive delegate result | DelegateExecutor caller / parent subagent result | Yes |
| Verify filesystem/tests | Declared WorkLedger verifier or model/tool evidence | Partial; no universal independent verifier |
| Retry/recover | Inner loop guards, controller steps, delegate failover, RunStore recover | Partial; semantics differ by path |
| Terminal success | `complete_task` for autonomous ledger; process/result status for delegates; final text for chat | Multiple authorities |
| Terminal failure | Controller state, DelegateResult/Run state, Gateway request status, inner halt | Multiple authorities |
| Progress | Controller callbacks, bridge events, delegate event checkpoints, Gateway SSE | Yes, path-specific |
| Long-running survival | Gateway persistence/native journals/RunStore; controller itself is in-memory | Partial |
| Persist task state | WorkLedger/RunStore/Gateway/native JSON depending on path | Partial, fragmented |
| Resume after interruption | RunStore/native reconcile/resume where supported; one-shot CLI delegates do not resume | Partial |

Therefore **NO SINGLE COMPLETION AUTHORITY PROVEN**.

## JaegerAgent audit

`JaegerAgent` is fundamentally a conversational ReAct/tool loop (classification **A: conversational reasoning loop**). It can execute multiple tools sequentially and may run up to `max_iterations` with tool-call and turn-budget limits. It stops on final text/no tool call, interruption, context overflow, repetitive/empty output, tool budget, iteration exhaustion, or adapter/dispatch error. The stop signal is primarily model output and deterministic guards; it is not generally verified filesystem state.

It owns message history, provider calls, tool catalog refresh, tool dispatch, argument/result feedback, steering, interrupt handling, and per-turn telemetry. It does not inherently own a task/job objective, delegate routing, durable restart recovery, or universal completion verification. It can reach `delegate_task` because that is a registered tool, and it can create a child agent through `core/runtime/subagents.py`, but the child relationship is an integration around the loop rather than a capability of the loop itself.

Human approval is available through the host/tool protocol. Cancellation interrupts a local turn; external cancellation is delegated to the relevant adapter/controller. A plain `JaegerAgent` object does not survive process restart; its transcript and surrounding run/ledger may be persisted by the host.

## JaegerAgentController audit

Construction and call chain:

```text
autonomous_runner.run_autonomous / run_worker_goal
  -> JaegerAgentController(...)
  -> run_to_completion(goal, session_key, objective)
       -> _step() -> turn_fn (normally main._run_turn)
       -> inspect completion/error/ledger/stop
       -> continuation prompt and another _step()
       -> terminal AgentState
```

States are `INIT`, `RUNNING`, `AWAITING_APPROVAL`, `COMPLETED`, and `FAILED`. It supports a max-step budget, context compaction, stop requests, blocker/question classification, and progress callbacks. For non-isolated runs it brackets the process-wide `execution` state; for isolated children it leaves the parent execution state alone. It returns a packed output and reason, but the controller object itself is not persisted and does not reconstruct a running controller after process restart.

Completion is stronger than prose: `last_completion()` or a completed active ledger is required, and `complete_task` itself refuses unfinished items or failed attached verification. The controller still accepts a “settled” continuation outcome in cases where no further continuation prompt is produced, so its strongest guarantee applies to ledger-backed batch work, not every arbitrary goal. It does not itself select external delegates; it consumes a `turn_fn` that may call them. It does not independently inspect a delegate workspace unless the supplied ledger verifier does.

**Classification: PARTIALLY.** It is already the correct existing seam for autonomous “work until complete” behavior. What prevents it from being a universal authority is that ordinary chat does not enter it, Gateway text-only/native adapter paths have their own lifecycle, and delegate/native results are not automatically routed through its verification gate.

## Subagent audit

`delegate_task` creates a fresh `JaegerAgent` with fresh history and uses a child `ContextVar` to prevent recursive delegation beyond the configured depth. For batch-shaped subtasks it wraps the child turn in `JaegerAgentController`; otherwise it performs one child `drive_one_turn`. Optional `JAEGER_SUBAGENT_WORKTREE` creates a temporary `jaeger-subagent/*` git worktree, rebinds the project root, and finalizes/prunes only a provably empty clean tree. The default may share the parent repository root.

The child has isolated prompt/session context and inherited/filtered tool access. Progress is sent through the parent pipeline event bus for batch workers. Cancellation is cooperative through the turn/worker context; cleanup is best effort. The returned payload includes answer, state, steps, halt reason, and optional worktree result. The parent receives that payload, but no universal parent-side test or diff verification follows it. Thus subagents are **first-class children of the existing Jaeger execution machinery for batch mode**, but the parent can still know only “child reported completion” unless a ledger verifier or explicit parent tool checks the changed workspace.

## Delegate architecture

The registry currently registers nine runtimes: Claude, Codex, Cursor, Gemini, Grok, Hermes, Ollama, OpenClaw, and OpenCode. All use the same `DelegateRuntime` contract; the process-backed adapters use `SubprocessDelegateRuntime` with argv builders, bounded stdout/stderr, workspace `cwd`, timeout, cancellation, and one-shot `resume` unsupported. Codex requests use `codex exec --json --sandbox workspace-write -`; Hermes uses `hermes-agent --query=...` or `hermes chat -q`; OpenClaw uses `openclaw agent --message ... --json --timeout ...`.

| Delegate | Detection | Execution/result | Workspace/process | Verification/current availability |
|---|---|---|---|---|
| Claude/Codex/Cursor/Gemini/Grok/OpenCode | executable probe plus optional availability check | subprocess output mapped to `DelegateResult`; exit 0 → `completed` | separate process; request workspace becomes `cwd`; timeout kills | no universal artifact/test verifier; Phase 1 probe: Claude/Codex/Gemini/Grok available, Cursor/OpenCode unavailable |
| Hermes CLI | executable probe; credentials/environment allowed | subprocess summary/events | separate process; workspace `cwd` | no universal Jaeger verification; Phase 1 probe unavailable because detector hit Xcode-license/system-git failure |
| OpenClaw CLI | executable probe | JSON-capable subprocess, but generic runtime still treats exit/result status as completion | separate process; workspace `cwd` | no Jaeger-side objective verifier; Phase 1 CLI probe available status was true for installed OpenClaw service, not proof of coding task |
| Ollama delegate | executable/config gate and `JAEGER_OLLAMA_DELEGATE_MODEL` | subprocess adapter if configured | local flag is configuration, not proof of model/tool semantics | Phase 1 reports unavailable without model setting; Ollama server itself was live |

The levels remain distinct: probe success proves executable/configuration; `start`/stream/result proves a process returned a result; neither proves tools changed the requested files, tests passed, or the objective is correct. `DelegateExecutor` does provide durable Jaeger run transitions, streamed checkpoints, health observations, failover, and cancellation hooks. Its CLI command uses an **InMemoryRunStore**, so `jaeger delegate run` itself is not restart-durable.

No paid or credentialed coding delegate was live-tested in this audit. This was deliberate: the available coding agents require external credentials/provider work, and the brief prohibits paid API use without explicit authorization. The subprocess implementation and existing agent/delegate test suites were inspected; live delegated edit/test/completion evidence is therefore **NOT LIVE TESTED**.

## Hermes paths

Hermes appears in four separate roles:

```text
1. vendor/hermes-webui/server.py
   -> WebUI shell on :8790
   -> Jaeger adapter/bridge client

2. optional ~/GitHub/hermes-agent
   -> prepended by run-jaeger-webui.sh when present
   -> external WebUI implementation source

3. jaeger_agent.delegates.hermes
   -> hermes-agent/hermes subprocess adapter
   -> DelegateRequest/DelegateResult lifecycle

4. core/frameworks/hermes_native.py
   -> Hermes container discovery + ~/.hermes/jaeger-native-api.key
   -> authenticated native Runs API on container port 8645
   -> streamed events, approvals, cancellation, reconciliation
```

The WebUI and CLI delegate are different ingress paths. The native Runs adapter is a structured control/receipt layer around a Hermes-owned agent; it does not make Hermes tools or effects Jaeger-owned. Jaeger can send a bounded prompt, workspace/model metadata where the native contract supports it, receive events and a terminal receipt, and request cancellation. The inspected contract does not show a universal Jaeger post-run diff/test verifier or artifact import. Hermes therefore supplies execution evidence; completion correctness is only as strong as the native receipt or any explicit Jaeger verification tool invoked afterward.

## OpenClaw lifecycle

OpenClaw has the same split: a subprocess delegate (`openclaw agent ... --json`) and a native adapter (`core/frameworks/openclaw_native.py` / WebUI adapter). The HTTP adapter sends an OpenAI-compatible chat request or, when `OPENCLAW_ADAPTER_NATIVE_RUNS` is enabled, a structured Runs request. OpenClaw owns its model, tools, effects, and gateway state. Jaeger receives text/events/status and persists a presentation/control receipt; reconciliation handles uncertain outcomes. A live `18789` listener proves service presence only. No Jaeger-side filesystem/test verification was found in the OpenClaw completion path.

Hermes and OpenClaw are architecturally compatible as external execution providers, but neither is a substitute for Jaeger's product-level completion authority.

## Native Runs backends versus delegates

| System | Problem solved | Caller/lifecycle | External launch | Persistence/events | Completion/tools/workspace |
|---|---|---|---|---|---|
| Native Runs backend table | Uniform structured Runs API for solo runtimes (`jaeger`, `hermes`, `openclaw`) | WebUI adapter/`RunsHTTP`; run journal with cancel/reconcile | Jaeger backend uses native MCP/turn; Hermes/OpenClaw call external services | JSON run journals, streamed events, approvals, cancellation, reconciliation | Claims native capabilities; knows run/session/workspace fields; verification is receipt/reconcile, not objective proof |
| Delegate registry/executor | Capability-selected external CLI/process runtimes and failover | CLI, Gateway handoff, `delegate_task`; `DelegateRequest` + Jaeger `Run` | Yes, subprocess adapters | RunStore checkpoints, health observations, streamed output | Knows workspace/cwd, timeout, result status; generic executor does not inspect artifacts/tests |

Classification: **PARTIALLY OVERLAPPING**, not proven duplicate. Native Runs is a protocol-facing run/control journal; delegates are a capability/routing/lifecycle port. They can conceptually coexist, but Hermes/OpenClaw are represented in both, so the boundary is easy to misunderstand and should be treated as an unresolved ownership seam.

## Tool and effect authority matrix

| Execution path | Jaeger ToolDef registry | Jaeger effect ledger | External tool system | Verification |
|---|---:|---:|---|---|
| Native Jaeger (`main` → JaegerAgent) | Yes | Yes when state/run bound | None required | Tool/ledger checks; objective only with WorkLedger |
| Jaeger subagent | Yes, filtered/inherited | Yes for child Jaeger tools | None required | Child ledger can verify; parent independent verification not automatic |
| JaegerAgentController | Via its `turn_fn`/inner JaegerAgent | Via inner run/tools | May call delegate tool | `complete_task` + ledger verification for batch goals |
| Gateway lead MCP | MCP tool catalog; target runtime decides dispatch | Not necessarily Gateway process ledger | MCP/Agentgateway target tools | Native receipt/result; no universal objective verifier |
| Gateway specialist/text-only Ollama | No Jaeger tools in direct `/api/chat` path | No | Ollama model only | Response text only |
| Delegate CLI | No, unless delegate itself is Jaeger | No shared Jaeger effect ledger | Delegate-owned tools/actions | Exit/result status only in generic executor |
| Hermes native Runs | No local Jaeger ToolDef dispatch | No shared local ledger | Hermes tools/effects | Hermes/native receipt and reconciliation |
| OpenClaw native/legacy | No local Jaeger ToolDef dispatch | No shared local ledger | OpenClaw tools/effects | OpenClaw status/receipt; no universal workspace verification |
| Ollama model provider | Only if used inside JaegerAgent | Inherited from JaegerAgent if so | Model server | Depends on host loop; direct Gateway fallback is text-only |

Jaeger therefore has several effect concepts: local `EffectLedger`, delegate-owned effects, Hermes/OpenClaw native effects, and transport/native run receipts. The local ledger prevents duplicate authoritative calls; it does not make external effects atomically part of Jaeger's ledger.

## Current authority graph

```text
User
 |
 +--> CLI / bridge / WebUI adapter
 |       [P transport/session]
 |       |
 |       +--> main._run_turn -----------------------------+
 |       |       [T ordinary turn]                         |
 |       |       +--> JaegerAgent + drive_one_turn [T]     |
 |       |       |       +--> JaegerOS ToolDef [E]         |
 |       |       |       +--> EffectLedger [E]             |
 |       |       |       +--> delegate_task [D] -----------+--> subagent JaegerAgent
 |       |       |                                              +--> Controller [J]
 |       |       |                                              +--> optional worktree
 |       |       |                                              +--> child ledger
 |       |       +--> optional JaegerAgentController [J,V]
 |       |
 |       +--> Gateway :8810 [P, session/SSE]
 |               +--> lead MCP :8811 --> native target [D/T]
 |               +--> specialist/text_only --> Ollama [T only]
 |               +--> handoff --> DelegateExecutor [D,P]
 |
 +--> DelegateExecutor [D,P]
 |       +--> subprocess delegate (Hermes/Codex/etc.)
 |       +--> external effects/state owned by delegate
 |
 +--> Native Runs adapter [T,P]
         +--> Jaeger native
         +--> Hermes native
         +--> OpenClaw native

[V] verification is split: WorkLedger verifiers, native receipts, delegate status,
and model/tool evidence. No single verifier covers every branch.
```

## Completion and false-completion risks

The strongest path is `complete_task`: it requires evidence, complete ledger items, and attached verification receipts. The controller will continue after ordinary “done” prose when the ledger remains open. This is a real safeguard.

The weaker paths remain material:

* `JaegerAgent` final prose is a successful turn even if a requested repository objective is unfinished.
* Generic subprocess delegate exit code `0` becomes `DelegateResult(status="completed")`; the generic layer does not prove a file edit or test result.
* Native Hermes/OpenClaw completion is an external receipt and may be `execution_unknown` until reconciliation; it is not a Jaeger objective proof.
* Gateway direct Ollama text-only execution can answer an action-capable request without tools or effects if routing metadata selects that branch.
* Asynchronous Gateway persistence, native journals, and delegate RunStore records settle different lifecycles; a transport terminal event is not necessarily objective completion.

## Failure injection and safe testing

No paid/provider coding run was invoked, and no real repository was given to an external agent. The safe evidence available is implementation and contract coverage:

* `packages/jaeger-agent/tests` — 908 passed.
* JaegerOS suite — 283 passed.
* Root smoke — 169 passed.
* Gateway/adapter targeted tests — 50 passed.
* WebUI server-control tests — 8 passed.
* Swift product build — passed after granting Xcode cache access.

The delegate runtime code explicitly handles missing executable (probe/start error), nonzero exit (`failed`), timeout (kills child, `failed`), cancellation (terminate/kill and `cancelled`), bounded output, and malformed/unstructured output (summary fallback). `DelegateExecutor.execute_with_fallback` reopens blocked/failed runs and tries the next candidate; a single delegate failure remains blocked. `resume()` is intentionally unsupported for one-shot CLI runtimes. These are code-level guarantees, not live fixture observations.

The requested temporary calculator fixture, parent/subagent live edit/test, and failure-injection matrix are **NOT LIVE TESTED** because all currently eligible coding delegates require external credentials or provider execution, which was not authorized. No credentials were printed and no temporary instrumentation was left in the repository.

## Minimum consolidation seam

The smallest existing seam that could eventually receive every action-capable request is **`JaegerAgentController` backed by `WorkLedger`**, with `JaegerAgent` remaining its inner turn engine. Evidence: it already owns repeated steps, continuation, stop/failure states, progress, and ledger-gated completion. It is already used by autonomous and batch subagent paths.

This is an audit conclusion only. No routing was changed. The current blockers are that ordinary chat bypasses the controller, Gateway text-only/MCP/native paths have separate completion semantics, and external delegate/native effects are not automatically subjected to Jaeger-side verification.

## Severity summary

### P0

None proven.

### P1

1. **No single completion authority across all actionable paths.** Interactive chat, Gateway direct Ollama, delegate executors, native Runs, and controller-backed autonomous work can each produce terminal results with different evidence standards.
2. **Action-capable request can reach text-only Gateway/Ollama.** The branch is selected by specialist/text-only session metadata and has no Jaeger tools, ledger, delegates, or objective verifier.

### P2

1. Delegate/native external effects are outside Jaeger's local effect ledger and lack universal post-run workspace/test verification.
2. `JaegerAgentController` is not restart-durable as an object; persistence exists below it and varies by path.
3. CLI delegate runs use `InMemoryRunStore`, so a process restart loses that command's run lifecycle.
4. Parent subagent completion can remain a child claim unless a ledger verifier or explicit parent inspection follows it.

### P3

1. Native Runs and delegate registries both represent Hermes/OpenClaw, creating a partially overlapping ownership vocabulary.
2. Capability probe, process success, delegate status, and task correctness are exposed as adjacent concepts and can be conflated by callers.

## Final answer in plain English

Jaeger already contains the beginnings of the right authority: `JaegerAgentController` plus `WorkLedger` can keep a bounded task moving and refuse completion until declared work and verification pass. That authority is used for autonomous and batch subagent work, not every user request. Normal chat still ends when the model produces an answer, and external Hermes/OpenClaw/delegate paths report their own execution status outside Jaeger's local effect and verification system. The repository therefore has a viable completion seam, but the current architecture does not prove one product-wide owner that knows every requested task is actually finished.
