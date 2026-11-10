# Jaeger agent framework: ownership and acceptance

Jaeger is one product with a shared framework beneath the Mac app and web UI.
A model change must not replace the conversation, execution authority, or event
history. This document is an acceptance contract, not evidence that a release
has passed. Record the tested revision and live receipts separately.

| Part | Authoritative implementation | Required behavior |
| --- | --- | --- |
| Models | `core/models/request_policy.py`, `packages/jaeger-agent/jaeger_agent/adapters`, `loop/runtime_bridge.py` | Preserve the admitted provider/model and local-only boundary; apply the target model's context, output, sampling and reasoning controls. |
| Tools | `skill_registry/tool_selection.py`, shared tool registry and existing executor chain | Discover, describe and load admitted tools; keep schema visibility separate from execution permission. |
| Execution loop | `loop/jaeger_agent.py` | Model → validated tool calls → correlated results → model; no unpaired results, duplicate IDs or orphaned parallel effects. |
| State and memory | Gateway `session_store.py`, existing memory store, `cognition/sqlite_runs.py` and `sqlite_commitments.py` | Preserve conversation, task/run identity, durable effects and useful knowledge without a second state owner. |
| Permissions | Gateway approvals and existing Hooked/Checkpointing/Ledger/Direct executor chain | Require the request's own authority; recheck cancellation after waiting for approval and before effects. |
| Orchestration | `core/entity/runtime.py`, model routing policy, existing delegation and continuation owners | Coordinate declared providers and specialists without silently changing identity, permissions, or sending local-only context to a cloud fallback. |
| Reliability | Existing cancellation scope, interrupt watchdog, context guard, turn budgets and continuation | Bound output, context and retries; stop queued work on cancel; surface failures and recover without claiming a completed effect twice. |
| Events | Gateway event bus, `turn_parts.py`, shared UI event projection | Stream provider-exposed reasoning, answer text, tool activity and status notes in order; replay the same parts after reload with one final answer. |

Paths without a package prefix are under `jaeger_ai/`; loop, adapter and tool
selection paths are under `packages/jaeger-agent/jaeger_agent/`.

## Model control contract

- Context and output are distinct. The reserved output must equal the ceiling
  sent to the provider. An explicit smaller context must not be replaced by a
  guessed model maximum. Local Ollama uses native `/api/chat` with
  `options.num_ctx`; OpenAI-compatible `extra_body.options` is not enforcement.
- A model switch resets incompatible model-specific settings. Fallback targets
  use their own context and sampling, never a cloud model's large local KV cache.
- `reasoning_effort` is effort, not a promise of task difficulty or accuracy.
  `auto` and `provider` use the model default. Named levels are not universal.
  Native Ollama validates against `/api/show`; boolean-only thinking does not
  mean low/high. Unsupported explicit settings fail rather than being ignored.
- OpenAI uses `max_completion_tokens`, optional `reasoning_effort` and
  `verbosity`. Other compatibility endpoints retain their documented token
  parameter. Unset temperature/top-p stay unset instead of forcing hidden defaults.
- Anthropic uses native adaptive effort or an explicit legacy thinking budget,
  not both. The budget must fit inside output tokens. Signed thinking blocks
  are retained for tool continuations only for the originating model.
- First-progress grace is distinct from a stall after progress. Cold local
  inference may use a bounded grace; cancellation remains immediate. These
  orchestration arguments never become model API parameters.
- CLI backends own their model output limits and sampling unless their verified
  command-line interface exposes a control. Jaeger enforces process timeouts,
  turn/tool budgets and context admission. Explicit supported reasoning flags
  are forwarded; unsupported sampling/effort is rejected. Do not claim that an
  API max-token setting controls a CLI's generation.
- Native in-process engines can have different streaming capabilities. Expose
  actual deltas when available, otherwise completed provider-reported reasoning;
  do not manufacture a thinking transcript or present runtime status as reasoning.

## Combined acceptance journey

1. Start an isolated conversation through the real client → Gateway → runtime.
2. Select a configured local model; perform a bounded read-only tool request and
   check provider identity, call/result IDs, output, usage and observed context.
3. Repeat with a configured cloud model. Change model in the same conversation;
   retain history and permissions and recompute model-specific limits.
4. Discover and load a tool, request an effect in a scratch workspace, and test
   allow/deny/cancel. No effect may run after cancellation while awaiting approval.
5. Exercise tool failure, malformed arguments, concurrent calls, a transient
   provider failure and unavailable primary. Confirm bounded recovery and honest
   terminal status. Never use a fallback to bypass local-only policy.
6. Observe reasoning, commentary/status and tool activity before completion.
   Reload/reconnect and verify ordered saved parts and exactly one final answer.
7. Verify task/continuation and delegated cancellation ownership. Restart only
   owned Jaeger services; recover the same saved conversation and receipts.
8. Match source revision, tested artifact, installed bundle and running services.

Run `./scripts/verify.sh` for deterministic product contracts. Provider quality
is separate: use the pinned official BFCL multi-turn checker and frozen case
selection. A twelve-case diagnostic is not a leaderboard score. Report every
failure, not-run case, actual wire setting and provider constraint; compare
identical sampling before attributing score changes to framework code. A live
chat reply alone does not qualify the installed agent loop.
