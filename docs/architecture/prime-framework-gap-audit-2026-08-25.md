# Prime-framework architecture gap audit — 2026-08-25

## Scope

This audit compares the current JaegerAI agent/runtime contract with patterns
in three upstream implementations, pinned so the comparison is reproducible:

- Anthropic Claude Agent SDK `24956bbbd11a57a94583d2762279cfbf2b2a81b0`
- OpenAI Codex `21c58c90f2298587c6519e077d0692ce4c563d37`
- Hermes Agent `c0b5a8e15d4445c42e21532c08c61388c569ff9f`

It covers turn execution, budgets, context, persistence, delegation, and
operator recovery. It does not treat donor UI or provider-specific internals
as requirements.

## Incident that triggered the audit

Session `b551d2464982` stopped after 24 successful tool calls while answering a
read-only explanation request. Sixteen calls were terminal calls. No provider
failure or failover occurred. The safety fuse worked, but the model had no
advance notice of its remaining total-call budget and the raw halt became the
user-visible answer.

The runtime now:

1. injects a one-shot warning when four calls remain;
2. refuses execution beyond the hard 24-call safety cap;
3. closes dangling tool calls to keep the transcript valid;
4. removes tools and asks for a final best-effort synthesis;
5. retains structured `halt_code` / `halt_reason` telemetry so ARES can show
   the safety outcome independently of the useful summary.

This follows the shared prime-framework principle: budgets are explicit,
exhaustion is structured, and a bounded finalization path is preferable to a
raw internal stop string.

## Current capability matrix

| Capability | Current JaegerAI state | Audit result |
|---|---|---|
| Tool-free finalization after a turn budget | Added in this change; existing iteration wind-down is reused for the total-call cap | Restored |
| Remaining tool-call warning | Added at 20/24 calls | Restored |
| Structured halt outcome in ARES | Bridge telemetry existed; ARES now persists halt code/reason on the assistant row | Completed projection |
| Context compaction and overflow retry | Three-stage compaction plus reactive server-overflow retry in `JaegerAgent` | Present |
| Safe parallel tools | Read-only/path-disjoint batching in `_dispatch_parallel` | Present; old status text is stale |
| Mid-turn steering | `JaegerAgent.steer`, runtime bridge, and client transport | Present; old status text is stale |
| External-effect checkpoints | `set_effect_checkpoint` and `TurnExecutive` binding | Present; refactor status was stale |
| Claims/beliefs in turns | Runtime bridge constructs `TurnExecutive` with `SqliteKnowledgeStore` | Present; refactor status was stale |
| Isolated delegation | Sync, parallel, and background delegation with depth/concurrency guards | Present |
| Persistent session replay | Jaeger transcript persistence plus ARES bridge hydration | Present, but recovery UX is partial |
| Adaptive task budget | Fixed per-turn iteration/call ceilings; no intent-, time-, token-, or tool-cost envelope | Missing |
| Operator resume from a safety stop | State is retained and goals pause, but no first-class “continue this halted turn” control | Partial |
| Durable child-run lineage | Delegation is bounded, but child/parent run lineage is not a complete resumable execution tree | Partial |
| Stable minimal tool surface | Scoping infrastructure exists, but broad tasks can still spend many calls discovering the workspace | Partial |

## What the prime implementations do differently

### Claude Agent SDK

Claude exposes a task budget/max-turn contract to the running agent and returns
a structured max-turn outcome. The transferable idea is budget visibility,
not a particular numeric ceiling.

### OpenAI Codex

Codex treats a turn as a resumable event loop: it follows explicit follow-up
state, compacts during the turn when required, emits budget reminders, and
uses structured session-budget errors. The transferable idea is that
compaction, continuation, and terminal state are separate contracts.

### Hermes Agent

Hermes uses a high configurable turn ceiling and, on exhaustion, strips tools,
requests a final summary, retries that finalization once, then returns a
controlled fallback. The transferable idea is a bounded finalizer outside the
normal tool loop.

## Prioritized improvements still worth porting

### P0 — next reliability slice

- Replace the single fixed counter with a `TurnBudget` value object tracking
  iterations, total tool calls, elapsed time, estimated tokens, and optional
  per-tool cost. Keep 24 as the emergency fuse, not the planning interface.
- Include remaining budget in model context from the start of expensive turns,
  then warn at deterministic thresholds.
- Add a bounded retry to the tool-free finalizer and a distinct
  `finalization_failed` diagnostic when both attempts fail.
- Expose halt status and a “continue from saved session” action in Dispatcher,
  without reopening the regular Chat pane.

### P1 — execution quality

- Add intent-sensitive budgets: explanation/read-only requests should begin
  with a narrow tool surface and a smaller discovery allowance; implementation
  tasks may receive a larger envelope.
- Add a tool-policy controller that prices broad shell/search calls, detects
  repeated discovery, and asks the model to synthesize before the hard fuse.
- Persist parent/child run identifiers and child summaries for delegated work,
  making background work inspectable and resumable rather than only returned
  as a tool result.
- Make plan obligations and verification outcomes visible in Dispatcher from
  the existing commitment/run/effect stores.

### P2 — cleanup and observability

- Consolidate duplicated historical status documents into the canonical
  architecture status; several “deferred” entries describe shipped features.
- Record budget snapshots and finalizer attempts in run telemetry for tuning.
- Add benchmark cases for explanation-only requests, broad repository audits,
  repeated discovery, context overflow, and finalizer failure.

## Non-goals

- Removing the hard safety fuse. A configurable budget still needs an absolute
  backstop.
- Copying donor framework code or provider-specific protocol details.
- Moving runtime authority into ARES. Jaeger owns execution and durable state;
  ARES projects it into mission-control UI.
