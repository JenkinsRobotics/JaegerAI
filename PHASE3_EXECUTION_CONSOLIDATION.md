# Phase 3 — Execution Consolidation

**Date:** 2026-09-15
**Checkout:** `main` at `612d6ee3afb1e4f2e59b83d831eddb35d43af1df`
**Purpose:** route actionable work through the existing `JaegerAgentController` + `WorkLedger` authority while preserving lightweight conversation.

## Files changed

* `jaeger_ai/core/runtime/autonomous_runner.py`
  * Added the existing routing seam `is_actionable_request`.
  * Extended autonomous classification to explicit state-changing, delegation, and verifiable-work requests while retaining conservative conversational negatives.
* `jaeger_ai/main.py`
  * Added `_run_actionable_turn`, which reuses `JaegerAgentController` and calls the existing `JaegerAgent` loop for each controller step.
  * Added a recursion guard so controller steps cannot create nested controllers through `_run_turn`.
  * Non-actionable requests continue directly to `_run_turn_via_jaeger_agent`.
* `jaeger_ai/core/gateway/server.py`
  * Actionable requests marked `text_only` are promoted to the existing native MCP route; they cannot silently fall through to direct Ollama prose.
* `packages/jaeger-agent/jaeger_agent/delegates/executor.py`
  * Delegate results now carry explicit `execution_completed` and `objective_verified=False` metadata. Runtime completion is clearly evidence, not objective proof.
* `dev/tests/jaeger_ai/core/test_autonomous_runner.py`
  * Added classification boundary tests.
* `dev/tests/jaeger_ai/core/test_gateway_daemon.py`
  * Added the actionable text-only promotion test.

No new engine, ledger, state machine, provider abstraction, or delegate framework was added. Hermes, OpenClaw, Native Runs, and the existing delegate contract remain intact.

## Previous semantics

```text
request
  -> main / Gateway / bridge
  -> JaegerAgent + drive_one_turn
  -> final prose or tool result

some batch/autonomous paths
  -> WorkLedger + JaegerAgentController

Gateway text_only
  -> direct Ollama /api/chat
  -> prose terminal result, even when the request described work
```

Delegate `status="completed"` was already a process/run result, but callers could read it without an explicit machine-readable distinction from objective completion.

## New semantics

```text
request
  -> existing actionable classifier
       ├─ conversation -> JaegerAgent -> answer
       └─ actionable
            -> ensure existing WorkLedger
            -> JaegerAgentController
                 -> JaegerAgent / drive_one_turn
                      -> JaegerOS tools
                      -> subagents / delegates
                 -> continuation until complete_task + verification,
                    blocker, cancellation, failure, or budget
            -> structured terminal result

Gateway text_only + actionable
  -> native MCP Jaeger route
  -> no direct Ollama prose fallback
```

Ollama remains a valid model provider inside JaegerAgent and remains valid for genuinely text-only Gateway requests.

## Actionable routing rule

`is_actionable_request` uses the existing autonomous routing module. It recognizes explicit state-changing/verifiable work (for example create/modify/fix/run tests/delegate/verify existence) and existing batch/`/goal` signals. It is deliberately not a giant keyword classifier and keeps explicit conversational forms such as “What is the capital of Egypt?”, “Explain this function”, and “Reply exactly …; do not use tools” lightweight.

When the classifier opens a ledger, `_run_actionable_turn` constructs the existing controller. The controller’s `turn_fn` is the existing `_run_turn_via_jaeger_agent`, so there remains one inner JaegerAgent loop. A ContextVar prevents recursive controller dispatch during controller steps.

## Conversational routing rule

Informational turns bypass the controller and ledger creation. They retain the previous `main` → `JaegerAgent` → provider → answer behavior. Existing explicit text-only requests also remain direct text-only requests when they are not actionable.

## Controller and WorkLedger integration

The controller receives the original objective and session key, then performs repeated inner turns. Existing `WorkLedger` acceptance guidance is injected by `prepare_turn_text`; `complete_task` remains the only successful ledger completion operation and still requires evidence, complete items, and attached verification. Controller failure, blocker, cancellation, and budget states are surfaced as an error/incomplete result rather than being printed as successful task text.

## Delegate evidence handling

`DelegateExecutor` now annotates every returned `DelegateResult` with:

```json
{
  "execution_completed": true,
  "objective_verified": false
}
```

The first field describes the delegate run. The second remains false until a caller’s objective-specific verification path establishes the postcondition. This preserves external ownership of Hermes/OpenClaw/Codex/etc. effects and does not pretend they passed through Jaeger’s local `EffectLedger`.

## Verification behavior

Native Jaeger actionable work can use the existing WorkLedger verification kinds and receipts, including declared path existence and other registered verification hooks. The controller will not accept final prose alone while the ledger is incomplete. Delegate completion is evidence supplied to the task; the task must still record relevant evidence and satisfy its verifier before `complete_task` succeeds.

This phase does not hard-code a universal test command. Repository-specific commands remain an objective/verifier concern.

## Gateway text-only protection

The Gateway now computes the same actionable intent signal for a request. If session metadata says `execution_mode=text_only` but the request is actionable, the Gateway attempts the existing native MCP route. If native execution cannot be confirmed, it records failure/unknown rather than calling direct Ollama and claiming completion. Non-actionable text-only requests keep the direct Ollama path.

## Subagents

Existing subagent behavior is preserved. Batch-shaped children already use `JaegerAgentController`; each child gets a fresh JaegerAgent and optional isolated git worktree. Parent verification remains objective-specific: a child result is evidence, not automatic proof of the parent objective.

## Hermes and OpenClaw

No adapter was rewritten. Hermes and OpenClaw remain pluggable external execution providers through their existing delegate and Native Runs paths. Their receipts/events/status can be attached as objective evidence, but their external effects remain outside Jaeger’s local EffectLedger. Jaeger’s WorkLedger/verifier determines the Jaeger objective when an actionable request requires verification.

## Ollama

Ollama remains available in three legitimate roles: a model provider inside JaegerAgent, a direct Gateway model-only responder for non-actionable text-only requests, and an optional delegate runtime. The new guard prevents the second role from receiving an actionable request silently.

## Persistence and durability limits

The change reuses existing persistence only. WorkLedger and Jaeger RunStore/native journals retain the state they already support. The controller object itself remains process-local; full controller reconstruction after process restart is not implemented in this phase. CLI delegate commands still use their existing in-memory run store. Client disconnect does not define objective completion.

## Tests added and executed

Added:

* informational versus actionable classifier boundary tests;
* Gateway actionable text-only promotion test.

Executed:

* focused autonomous/Gateway tests — passed;
* `packages/jaeger-agent/tests` — **908 passed**;
* root smoke — **169 passed**;
* JaegerOS suite — **283 passed**.

No paid APIs were called. No external coding delegate was given a real repository or credentials. Live provider edit/test verification remains a follow-up test activity when a safe local delegate is explicitly available.

## Remaining architecture debt

1. Gateway native MCP, bridge/main, Native Runs, and external delegate paths still have different transport lifecycles; this change prevents the known text-only escape but does not collapse those protocols.
2. Parent-side verification after an arbitrary external delegate remains explicit/task-specific rather than automatic.
3. Controller restart recovery remains a separate persistence phase.
4. The classifier is intentionally conservative; structured ingress metadata should remain the preferred signal where available.

The consolidation uses the existing authority seam and leaves simple conversation lightweight.
