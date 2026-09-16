# Phase 4 — Adversarial Execution Validation

**Date:** 2026-09-15
**Repository:** `/Users/matthewjenkins/GitHub/JaegerAI`
**Checkout:** branch `main`, HEAD `612d6ee3afb1e4f2e59b83d831eddb35d43af1df`
**State:** heavily dirty; Phase 3 files and many unrelated user edits are uncommitted. No reset, clean, or discard was performed.

## Plain-English verdict

**VERIFIED WITH LIMITATIONS.**

If Jaeger receives a clearly actionable request through the local `main` turn path, it now enters `JaegerAgentController` with a `WorkLedger`; simple informational prompts remain one inner `JaegerAgent` turn. Final prose cannot satisfy an incomplete ledger. The Gateway no longer silently sends an actionable `text_only` request to direct Ollama. Delegate execution status is correctly separated from objective verification.

The remaining limitations are real: live external coding-agent execution was not authorized, controller restart reconstruction is not implemented, and external Hermes/OpenClaw effects remain outside Jaeger’s local effect ledger. A real multi-agent fixture run is the next phase.

## Phase 3 diff audit

| Change | Why | Result |
|---|---|---|
| `is_actionable_request` in `autonomous_runner.py` | Existing autonomous routing needed a single actionability seam | Initial implementation was too broad/narrow; fixed after 100-row adversarial corpus |
| `_run_actionable_turn` in `main.py` | Reuse existing controller/ledger without replacing the inner loop | One top-level controller; ContextVar blocks recursive promotion |
| Gateway text-only guard | Prevent action requests reaching model-only Ollama route | Actionable text-only requests promote to native MCP or fail; non-actionable text-only remains allowed |
| Delegate metadata in `DelegateExecutor` | Make process completion distinct from objective completion | Correctly status-derived for all returned terminal results |

No second engine, ledger, controller, agent loop, provider system, or verification framework was introduced.

## Actionability classifier

Created [CLASSIFIER_VALIDATION_MATRIX.md](CLASSIFIER_VALIDATION_MATRIX.md) with 100 cases across pure information, direct action, discussion, negation, mixed requests, delegation, verify-only, text-only, quoted commands, and declarative prose.

The first adversarial evaluation found 8 mismatches. The corrected classifier now produces **0 mismatches / 100 rows**. It recognizes direct commands (`Create`, `Run pytest`, `Commit`), delegation (`Have Codex...`), verification (`Confirm port...`), and mixed action; it rejects questions, “how to” discussion, negation, quoted commands, and documentation examples.

Ambiguous read-only inspection is treated as observable actionable work when it asks Jaeger to inspect and report state. Explicit structured ingress metadata remains preferred.

## Conversational-path proof

The classifier returns conversation for “What is the capital of Egypt?”, “Explain this function”, “Compare Hermes and OpenClaw”, and the discussion/negation corpus. `main._run_actionable_turn` returns `None` for these, so `_run_turn` calls `_run_turn_via_jaeger_agent` directly. No ledger/controller is created by this routing seam.

Existing lightweight worker and autonomous tests continue to pass. No delegate is probed by the conversational routing function.

## Actionable-path proof

For an actionable request, `_run_turn` calls `should_run_autonomous`, `ensure_autonomous_ledger`, then constructs the existing `JaegerAgentController`. Its `turn_fn` calls `_run_turn_via_jaeger_agent` directly, which calls `drive_one_turn` and the existing `JaegerAgent`. Controller continuation then evaluates ledger/completion state. A dedicated test sets `_actionable_controller_depth=1` and proves a controller step cannot create a nested top-level controller.

The controller’s non-completed state is converted into an error/incomplete result, preventing a failed or budget-exhausted actionable run from printing a successful answer.

## Temporary fixture methodology and native work test

The requested calculator fixture was not used against the Jaeger repository. A live model-driven fixture run was **NOT LIVE TESTED** because the configured local model path is unresolved in `jaeger doctor`, and external coding delegates require credentials/provider execution. No paid API or external agent was invoked.

Deterministic controller/ledger coverage exists in the autonomous test suite: workers repeatedly update a ledger, continue after settled prose, and only settle after `complete_task`. WorkLedger verification tests cover path/receipt rejection and acceptance. This proves orchestration semantics without pretending to prove a live model edit.

## False-success and evidence tests

`complete_task` requires evidence, complete ledger items, and attached verification; a model’s “Done” cannot close an open ledger. Delegate results are annotated:

```json
{"execution_completed": (status == "completed"), "objective_verified": false}
```

The new parameterized tests cover `completed`, `failed`, `blocked`, and `cancelled`; timeout is represented by the subprocess runtime as `failed` after killing the child. Thus failed, timed-out, and cancelled results do **not** receive `execution_completed: true`.

A delegate’s successful process status is not promoted to `objective_verified`. Poor delegate prose can be outweighed only by an objective-specific WorkLedger verifier; no universal external-delegate postcondition verifier was added.

## Gateway text-only validation

Existing text-only behavior remains allowed for “hello”/informational requests and calls direct Ollama. The added Gateway test sets `execution_mode=text_only`, sends “Create calculator.py and run the tests”, stubs native MCP success, and makes `_ollama_chat` fail if called. Native is called and the terminal backend is `mcp:test`; direct Ollama is not used.

If native MCP is unavailable, the Gateway records failure/unknown rather than reporting a text-only action as successful.

## Delegate contract validation

`DelegateRuntime.probe` establishes capability/configuration only. `start`/stream/result establish process execution. `DelegateExecutor` persists checkpoints and Jaeger Run state, but objective correctness remains separate. Subprocess adapters enforce workspace `cwd`, bounded output, timeout, cancellation, and cleanup. One-shot CLI `resume` is unsupported.

The semantic audit specifically confirmed that the metadata is not blindly true: it is computed from `result.status == "completed"`. Exceptions before a `DelegateResult` are recorded as blocked/raised and do not receive completion metadata.

## Subagent validation

`delegate_task` creates a fresh JaegerAgent, isolates history/context, limits recursion, and optionally creates a temporary git worktree. Batch children use the existing controller. Child output is evidence returned to the parent; parent objective verification remains explicit and is not automatically inferred from child prose.

## Hermes, Codex, and OpenClaw status

Capability probes were used previously; no live coding-agent fixture was run. Hermes/OpenClaw paths require external services, credentials, or provider execution. Status: **NOT LIVE TESTED — AUTHORIZATION/COST BOUNDARY**. Their adapters remain unchanged and external effects remain external receipts, not Jaeger local effects.

## Cancellation and budget behavior

The existing controller transitions to `FAILED` on stop or exhausted budget, and the inner agent reports `interrupted`/budget halt. Delegate subprocess cancellation terminates then kills after a bounded wait. Native Runs preserve `execution_unknown` until reconciliation. None of these paths is mapped to product-level objective success.

## Verification failure and effect safety

Existing WorkLedger tests prove `complete_task` rejects missing/in-progress items and failed verification, then accepts once the verifier passes. Existing EffectLedger tests and the 911-test agent suite remain green; controller wrapping calls the same JaegerAgent executor, so native authoritative effects retain allowlists, checkpoints, and `EffectLedger.once` deduplication.

## Error propagation

* Inner tool/model errors become turn errors or halt reasons.
* Delegate exceptions transition the Jaeger Run to blocked and raise; non-completed returned results transition to their matching terminal state.
* Verification errors keep the WorkLedger incomplete and reject `complete_task`.
* Controller budget/stop/blocker states are surfaced as incomplete/error results.
* Gateway native-unavailable action requests fail/unknown rather than falling back to direct Ollama prose.

## Transport does not define completion

Gateway request rows, SSE terminal events, bridge replies, native journals, and delegate Run states are transport/execution receipts. The WorkLedger/controller completion gate remains separate. Client disconnect is not treated as objective completion; native uncertain execution is explicitly reconciled.

## Provider-role distinction

`JaegerAgent → Ollama` remains a model-provider path that can use Jaeger tools when hosted by JaegerAgent. `Gateway text_only → Ollama /api/chat` remains model-only and is now restricted to non-actionable requests. Hermes/OpenClaw/Codex/etc. remain agent/execution providers rather than being conflated with model providers.

## Concurrency and persistence

ContextVar recursion state is request-local. Existing RunStore lineage/checkpoint APIs and Gateway request IDs provide separate identities. Full concurrent two-fixture execution and controller restart reconstruction were not live-tested in this phase; controller objects remain process-local and CLI delegate commands still use an in-memory run store.

## Performance sanity

Informational requests take the `is_actionable_request` check and return directly to the existing inner loop. They do not create a ledger, instantiate a controller, probe delegates, or add a model call. Actionable requests intentionally incur ledger/controller work. No microbenchmark was necessary to establish the branch behavior.

## Security and authority sanity

The controller only governs continuation/completion. Tool allowlists, workspace validation, shell hooks, checkpoints, EffectLedger idempotency, delegate sensitivity/locality checks, and native approval/cancellation paths remain in their existing owners. No controller route bypass was introduced.

## Regression results

| Suite/check | Result |
|---|---:|
| 100-row classifier matrix | 100/100 expected classifications |
| Focused autonomous + delegate tests | 27 passed |
| Gateway targeted suite | 30 passed |
| Jaeger agent suite | **911 passed** |
| Root smoke | **169 passed** |
| JaegerOS suite | **283 passed** |
| Python compile/import validation | passed with enforced external pycache |
| Swift build | passed previously; no Swift changes in Phase 4 |

The initial focused run had sandbox socket-bind failures in aiohttp tests and one classifier mismatch; socket tests passed with host permissions and the classifier defect was fixed with regression coverage. The socket failures were environment restrictions, not production regressions.

## Defects discovered and fixed

1. **Classifier false positives/negatives (Phase 4 discovered regression in Phase 3 implementation).** Discussion, negation, and quoted-command prose could enter autonomous mode; direct commands could be missed. Fixed in `autonomous_runner.py` with declarative/negation/quote handling and direct imperative/verification recognition. Proved by 100-row matrix and tests.
2. **Delegate completion semantics:** audited, no defect found. `execution_completed` is status-derived and false for failed/blocked/cancelled/timed-out results. No production change required for this concern.

## Phase 3 claims matrix

| Claim | Verdict |
|---|---|
| Actionable requests use controller + WorkLedger | **PROVEN** on the local `main` turn path; external routes remain separate by design |
| Simple chat remains lightweight | **PROVEN** by branch logic, corpus, and regression tests |
| Text-only Gateway cannot silently complete actionable work | **PROVEN** by mocked call-count test |
| Delegate completion is evidence, not objective proof | **PROVEN** by contract and metadata tests |
| Final prose cannot complete ledger-backed work | **PROVEN** by WorkLedger/controller semantics and tests |
| Ollama still works as model provider | **PROVEN** by preserved provider paths and Gateway text-only tests |
| Hermes/OpenClaw remain external providers | **PROVEN** by unchanged adapter/native contracts |
| No second inner agent loop | **PROVEN** by direct controller turn function and recursion test |
| EffectLedger still protects native effects | **PROVEN** by existing agent suite and unchanged executor composition |
| Controller recursion is prevented | **PROVEN** by ContextVar guard test |

## Remaining risks

* No live external delegate fixture was authorized, so real Codex/Hermes/OpenClaw edit/test/retry behavior remains unverified.
* Controller restart recovery and universal parent-side post-delegate verification remain future work.
* The classifier is intentionally heuristic; structured client metadata should take precedence where available.
* The repository and current branch remain dirty; uncommitted unrelated changes may affect a clean-release result.

## Final answers

* **If I tell Jaeger to do something, does it stay responsible?** For clearly actionable local turns, yes through the existing controller/ledger; external routes still provide evidence that requires objective-specific verification.
* **Can it merely say “done” while incomplete?** Not for an open ledger-backed objective; ordinary conversation can still return prose because it is not a task contract.
* **Can a delegate say “done” and trick Jaeger?** Its status cannot set `objective_verified`; a verifier must establish the objective.
* **Can Gateway direct Ollama receive work requests?** Actionable text-only requests are promoted to native MCP or fail; they do not silently use direct Ollama.
* **Does simple chat behave normally?** Yes, verified across the classifier corpus and tests.
* **One inner JaegerAgent loop?** Yes; the controller calls the existing loop directly.
* **Did Phase 3 create stacked architecture?** No new stack was created; existing layers remain and their boundaries are documented.
* **Ready for real Hermes/Codex/OpenClaw workflows?** Ready for a controlled next phase, with the explicit authorization/cost and external-service limits above.
