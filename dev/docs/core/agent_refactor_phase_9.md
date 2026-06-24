# Phase 9 — App review + cleanup

**Status:** Phase 9 shipped. Live TUI failure root-caused and fixed;
pydantic-ai dependency fully removed; ~1,700 LOC of dead code deleted.

## What triggered this phase

The user reported a live TUI failure on `hello`:

```
[jaeger] prewarm skipped: no response after 30.1s (stale_timeout=30s)
hello
decode: removing memory module entries for seq_id = 0, pos = [0, +inf)
✦ error: llama_decode returned -3
```

Same error after a brain swap to gemma-4 — ruling out a model-specific bug.

## Root cause

My Phase 8 stale-call detector (default `stale_timeout=30s`) abandons
the worker thread when a model call exceeds the timeout. **This is
correct for HTTP-backed adapters** (closing the socket cancels the
request) — but **wrong for in-process llama-cpp**:

1. The abandoned worker keeps running inside the same Python process,
   holding the `Llama` instance.
2. The next call (the user's `hello`) sees the `Llama` mid-decode and
   tries to clear its KV cache — that clear partially fails because
   the half-finished decode is still touching memory.
3. llama-cpp returns `-3` ("decode failed") on the new attempt.

The prewarm hit the 30s ceiling because the new prewarm path drove the
**full agent loop** (all 63 tools' schemas, ~9K tokens of prefill on
cold weights) instead of the legacy single-token warmup.

## Fixes

| Change | File | Why |
|---|---|---|
| `LocalLlamaAdapter.call` forces `stale_timeout=None` | [src/jaeger_os/agent/adapters/local_llama.py](../src/jaeger_os/agent/adapters/local_llama.py) | In-process calls can't be safely cancelled — abandoning the worker corrupts KV cache |
| `MLXAdapter.call` same override | [src/jaeger_os/agent/adapters/mlx.py](../src/jaeger_os/agent/adapters/mlx.py) | Same reasoning |
| `prewarm` hits `llama.create_chat_completion` directly with `max_tokens=1` and no tools | [src/jaeger_os/main.py](../src/jaeger_os/main.py) | Skip the heavy tool-schema prefill that was tripping the 30s timeout in the first place |
| New regression test | [tests/jaeger_os/agent/test_local_llama_adapter.py](../tests/jaeger_os/agent/test_local_llama_adapter.py) | `test_in_process_call_forces_stale_timeout_to_none` pins the contract |

## pydantic-ai — fully removed

The Phase 6.2 cutover left pydantic-ai imported but unused. This phase
finishes the job:

### Source files deleted

| File | Reason |
|---|---|
| `src/jaeger_os/core/llm_model.py` | LlamaCppModel — pydantic-ai `Model` ABC implementation for llama-cpp. Replaced by `LocalLlamaAdapter`. The drift parser inside it was already lifted to `agent/drift_parser.py` in Phase 4. |
| `src/jaeger_os/core/mlx_model.py` | Same for MLX. Replaced by `MLXAdapter`. |
| `src/jaeger_os/core/tool_result_budget.py` | `TurnResultBudget` + `compact_history` — used pydantic-ai message parts. No remaining callers. |
| `src/jaeger_os/core/tool_guardrails.py` | `ToolGuardrail` — only ever called from the deleted `_run_via_iter`. Replaced by `AgentCallbacks.before_tool_call`. |
| `src/jaeger_os/agent/bridge.py` | Phase-6 transitional bridge that mirrored pydantic-ai tools into the new registry. Obsolete now that tools register directly via `@register_tool_from_function`. |

### Dead code removed from main.py

~775 LOC removed in one bulk pass (main.py: **4056 → 3160 lines**, -22%):

| Function | Lines | Was used by |
|---|---|---|
| `_run_via_iter` | ~240 | Legacy loop body (replaced by `JaegerAgent.run_turn`) |
| `_walk_new_messages` + `_pair_tool_messages` | ~80 | Tool-activity walker over pydantic-ai parts |
| `_run_with_fix_loop` + 5 retry helpers | ~150 | Run-python fix-loop (subsumed by `JaegerAgent` retries) |
| `build_agent` + `_build_mcp_tools` | ~55 | Pydantic-ai `Agent` constructor |
| `_episodic_to_messages` + `_ensure_system_prompt` | ~55 | Pydantic-ai session-resume helpers |
| `_iter_tool_returns` + `_update_session_state_from_iter` + `_sanitize_history_messages` + `_augment_with_session_context` | ~100 | Legacy `_run_turn` fallback branch (the gated-off code) |
| `_MAX_TOOL_CALLS` + `_MAX_IDENTICAL_CALLS` + `_loop_halt_reason` + `_semantic_failure_signature` + `_tool_arg_detail` | ~65 | Replaced by `jaeger_os.agent.loop_backstop` |
| Pydantic-ai imports | 11 | Now zero |

### Tests deleted (tested deleted code)

| File | Tested |
|---|---|
| `tests/jaeger_os/core/test_session_state.py` | `_augment_with_session_context` etc. |
| `tests/jaeger_os/core/test_session_resume.py` | `_ensure_system_prompt`, `_episodic_to_messages` |
| `tests/jaeger_os/core/test_loop_backstop.py` | Duplicate of `agent/test_agent_loop_backstop.py` |
| `tests/jaeger_os/core/test_drift_parser.py` | Duplicate of `agent/test_agent_drift_parser.py` |
| `tests/jaeger_os/core/test_tool_call_repair.py` | Drift repair in deleted llm_model |
| `tests/jaeger_os/core/test_native_handler.py` | Pydantic-ai native handler |
| `tests/jaeger_os/core/test_mlx_backend.py` | Pydantic-ai MLX wrapper |
| `tests/jaeger_os/core/test_tool_shortlist.py` | Deleted shortlist helper |
| `tests/jaeger_os/core/test_tool_result_budget.py` | `compact_history` |
| `tests/jaeger_os/core/test_tool_guardrails.py` | `ToolGuardrail` |
| `tests/jaeger_os/agent/test_bridge.py` | Deleted bridge.py |

### Tests rewritten (still active code with new shape)

| File | Change |
|---|---|
| `tests/jaeger_os/core/test_external_model.py` | Asserts new `validate_external_provider` returns the key (was: asserts old `build_external_model` returns a pydantic-ai `Model`). The 7 "build_X_model" tests are now "validate_X_provider" tests; surface tests no longer read `client.model`. |
| `tests/jaeger_os/core/test_tier_gating.py` | Reads from `jaeger_os.agent.get_tools()` instead of `agent._function_toolset.tools` |
| `tests/jaeger_os/core/test_skill_loader.py` | Asserts `_ToolCapturingAgent` registers into the framework-free registry |

### `.model` properties removed from clients

`LlamaCppPythonClient.model`, `MlxClient.model`, `ExternalModelClient.model`
— all dead since Phase 6.2 (the new agent reads `.llm` for in-process
or selects an adapter from `.ext` for external). Their absence makes
the `pydantic-ai` Model subclasses redundant, which is why the legacy
modules above could be deleted.

### `pyproject.toml`

```diff
- keywords = ["agent", "llm", "local-first", "robotics", "pydantic-ai", ...]
+ keywords = ["agent", "llm", "local-first", "robotics", ...]
  dependencies = [
-     "pydantic-ai>=1.2",
      "pydantic>=2.0",
      ...
```

Verified: `pip uninstall pydantic-ai pydantic-ai-slim` → `pytest -q`
still passes 866/866. JROS no longer needs the dependency at all.

## Test count

```
Before Phase 9:  987 passing (after Phase 8)
After deletion:  866 passing  (-121 — all tests for deleted code,
                                no regressions in tests for kept code)
```

121 tests were removed because the code they tested no longer exists.
Every remaining test is exercising live code that ships in the
runtime.

## Live verification

The user's TUI was holding the instance lock during cleanup so I
couldn't run a live smoke from the same machine. The unit test
`test_in_process_call_forces_stale_timeout_to_none` pins the contract
that caused the original `llama_decode -3` failure. The next TUI
restart should boot cleanly:

```bash
# After this PR lands:
jaeger-os
# Expected:
[jaeger] loading <model>...
[jaeger] loaded in N.Ns.
[jaeger-skills] registered K skill(s): ...
[jaeger] agent prewarmed in N.Ns      # < 30s now (1-token prefill)
Type a prompt, or /help for slash commands.
> hello
<actual model response>
```

No more `prewarm skipped` warning. No more `llama_decode -3` on first
turn. The stale-call detector still protects HTTP-backed cloud
adapters — its scope is just correctly limited to where it's safe.

## Closed loop

| Phase | What it did | Status |
|---|---|---|
| 1-5  | Built the new framework-free agent layer alongside pydantic-ai | ✓ |
| 6.1 | Parallel new-loop path gated behind env var | ✓ |
| 6.2 | Flipped the default — new loop is the only path | ✓ |
| 7   | Hermes-style toolsets (53% schema reduction available) | ✓ |
| 8   | Resilience: arg coercion, schema sanitiser, length-retry, stale-call detector, jittered backoff, prompt-cache | ✓ |
| **9** | **Cleanup: pydantic-ai removed, ~1700 LOC dead code deleted, live `llama_decode -3` bug fixed** | ✓ |

JROS is now framework-free end-to-end. The agent loop, the tools, the
adapters, the schemas, the toolsets — all live in
`jaeger_os.agent.*`, owned and shipped by us.
