# Code review (2026-05-24) — what landed, what deferred

External review found 10 issues. This doc records the disposition and
the reasoning for each.

## Applied this round

| # | Finding | Fix |
|---|---|---|
| 1 | History trim could split assistant `tool_calls` from matching tool results | `ContextGuard._head_group_size` drops in groups — assistant + every following tool message whose `tool_call_id` matches one of its calls. 3 new tests in `test_context_guard.py`. |
| 2 | `AgentInterrupted` returned empty assistant message without setting `last_halt_reason` | Both interrupt sites now set `last_halt_reason="interrupted"`. Unified the string across the two sites (was "the turn was interrupted" in one, missing in the other). |
| 3 | `reset_read_tracker()` never called by Phase-9 `run_turn` | Called at the top of every `run_turn`, before the user message append, so a legitimate next-turn re-read isn't suppressed. |
| 6 | `normalize_tool_name` existed but no caller at the loop boundary; raw drifted names hit dispatch | `_dispatch_one_tool` now normalises once against `self._all_tools` before the `has_tool` check. The `tool_call` dict is patched in place so backstop bookkeeping sees the corrected name. |
| 7 | Skip-final could end multi-step turns prematurely | Added `_looks_multistep(user_message)` heuristic — patterns like "and then", "first … then", "step 1 … step 2" suppress the short-circuit. Conservative bias: false positives just take the full loop (one extra model call), false negatives silently drop user work. |
| 8 | Generic exception catch lost permission/safety types; Three Laws block existed but wasn't wrapping the system prompt | Tool dispatch now sets `error_type` + `retryable` + (when applicable) `required_tier` on the result dict; `PermissionDenied` / `ConfirmationRequired` / `HumanOverrideRequired` are tagged `retryable=false`. `build_system_prompt` wraps with `with_three_laws(...)` so the safety frame is the first block. |
| 10 | Latency log fields zeroed for the new path | Tool-progress callback in `main.py` accumulates per-turn tool time; the `LatencyReport` now carries `tool=tool_time` and `decision=loop_time` (total minus tool time) instead of both being 0. Adapter-level per-phase timings (TTFT, decision-vs-final split) still need adapter cooperation — separate follow-up. |
| 9 | Toolset default exposed everything | Already addressed by the **lean tool surface** work that landed earlier today — `agent.tools` is now a property that filters through `tool_visible()` per access. CORE + catalog by default; `JAEGER_FULL_TOOLS=1` is the bench escape hatch. See `docs/lean_surface.md`. |

Also fixed two bugs the user spotted in the TUI status bar (independent
of the review):

- **Loaded-ctx vs config-ctx**: `_current_ctx_max()` now prefers
  `client.loaded_ctx` over the wizard's `config.model.ctx`, so a model
  loaded at a different ctx is reflected immediately. New
  `_current_native_ctx_max()` surfaces the model's trained max
  (`n_ctx_train`), and `/runtime` flags it when the loaded ctx is more
  than 2× below native ("Qwen3-Coder-30B at 16K loaded but 262K trained
  — bump config.model.ctx").
- **0% gauge**: `_refresh_context_estimate` only walked the legacy
  pydantic-ai `msg.parts[].content` shape. The Phase-9 agent produces
  plain TypedDicts with `msg["content"]` directly — the estimator
  returned 0 for them, so the gauge stayed at 0%. Now handles both
  shapes. 4 new regression tests in `test_tui_rendering.py`.

## Deferred — with explicit reasoning

### #4 — Tool-guardrail controller wiring

Hooks (`on_before_tool_call` / `on_after_tool_call`) exist in
`AgentCallbacks` and are fired by `_dispatch_one_tool`, but `main.py`'s
`AgentCallbacks` construction only wires `tool_progress` and
`heartbeat`. A guardrail controller that detects repeated no-progress
calls / repeated failures / permission-denied retries would be a
medium-effort addition: it needs its own state, careful "does this
mirror or duplicate the loop-backstop" design, and tuning against the
benchmark suite to avoid regressing routing accuracy.

**Why deferred:** the loop-backstop already exists and catches the
worst case (identical-call hammering, semantic failure repeats). The
incremental value of a richer guardrail is real but small; building it
right is a focused work item, not a side change inside this review's
pass. Plan: lift Hermes's `tool_guardrails.ToolGuardrailController`
behind a feature flag, A/B against the benchmark, ship if it improves
L2/L4 numbers without regressing L1.

### #5 — Safe parallel tool execution

Read-only / path-disjoint tool batches could run in parallel; the
current dispatcher is sequential. Hermes does this carefully — they
exclude interactive, dangerous, computer-control, and robot tools, and
they preserve result order.

**Why deferred:** medium effort with subtle correctness ground.
Concurrent dispatch needs:

  - A clear policy for "what's safe to parallelise" (the `interactive`
    / `dangerous` flags on `ToolDef` are the obvious source — but
    `read_only` would need adding, and path-disjointness is per-call).
  - Result-order preservation so the model sees deterministic message
    ordering.
  - Interrupt semantics that don't strand a half-launched batch on
    cancel.
  - Bench data showing it moves L2/L4 meaningfully on local models.

Skipped this pass; tracked for a focused follow-up once the
already-landed wiring (group-aware trim, normalised names, tool-time
telemetry) gives us a clean baseline to measure against.


---

# Second review (external, post-0.1.0)

A second external code review came in after 0.1.0 shipped with 14
prioritised findings. Most landed as small focused fixes; a few are
explicitly deferred below with the reasoning that drove the decision.

## Applied (no deferral)

| # | Finding | Fix |
|---|---|---|
| 1 | `reload_skills` `NameError` — `agent` symbol missing in `_register_builtins` scope after Phase-9 | Pass a fresh `_RegistrationSentinel()` (the legacy `agent` was a pydantic-ai Agent that no longer exists). |
| 2 | `/new` / `/undo` / `/retry` didn't touch `JaegerAgent.messages` (the Phase-9 storage location) | `reset_session` clears both legacy `_session_histories` AND the agent's messages; `pop_last_exchange` prefers the agent path, falls back to legacy for hybrid sessions. 7 new tests. |
| 3 | Explicit `tools=[...]` allowlists weren't enforced at dispatch — model could call any globally registered tool | `JaegerAgent.__init__` builds a per-instance `_dispatch_by_name` map from `_all_tools`; `_dispatch_one_tool` resolves against it instead of the global registry. |
| 6 | `schedule_prompt` / `cancel_schedule` were tier-0 despite the autonomous-effects-of-effects argument | Both gated at `WRITE_LOCAL`. Scheduled execution still re-enters the tier ladder for whatever tools it calls. |
| 7 | Drift parser bailed on text without `<` — Llama raw JSON and Mistral `[TOOL_CALLS]` formats lost | Added `_extract_llama_raw_json_tool_calls` (with `<|python_tag|>` and bare-JSON shapes) and `_extract_mistral_tool_calls` (pre-v11 array + v11+ interleaved). Defensive against misclassifying Hermes envelopes as Llama. 5 new tests. |
| 8 | OpenAI adapter dropped malformed `arguments` to `_raw_arguments` instead of using `repair_arguments` | `_from_openai_tool_calls` calls `repair_arguments` on JSON decode failure; only falls through to `_raw_arguments` if repair also fails. |
| 9 | `TOOLSETS["code"]` said `run_python` but the tool was renamed `execute_code` — masked by fail-open | Fixed the name in `core/skills/toolsets.py`. Added a defensive integrity test that every registered tool is either in `CORE`, in a `TOOLSETS` bucket, or on an explicit `_INTENTIONAL_FAIL_OPEN` allowlist. Future renames will surface immediately. |
| 11 | `describe_tool` defined in both `meta.py` and `main.py`; `load_toolset` trapped in `main.py` | Both now owned by `meta.py` (single source of truth), registered at module-import time via `@register_tool_from_function`. The main.py duplicates are removed. |
| 13 | `SKIP_FINAL_TOOLS` included mutating writers (`write_file`, `append_file`, `patch`, `delete_file`) — could end a "fix typo" turn after the first write | Removed those four from the set. Read/list ops + deterministic-answer tools stay. The multistep intent check still handles edge cases. |
| 14 | No tests for `/new` / `/undo` / `/retry` on the new agent path | Added `tests/jaeger_os/core/test_session_commands.py` — 7 tests covering both clears, both fallback paths, and the edge cases (empty session, assistant-only session, in-flight tool chain). |

## Deferred — with reasoning

### #4 — Daemon streaming-client + event correlation (before Phase 2)

`Client.call()` is request/response only; events that arrive while
waiting are dropped. The Phase-2 permission flow needs a persistent
streaming connection with an event callback queue and id-based
response correlation.

**Why deferred:** Phase 2 of the daemon split isn't started yet —
no real caller is yet exercising the limitation. The streaming
client is on the Phase 2 critical path; better to design it
alongside `submit_turn` than to retrofit a one-shot socket. Tracked
in `docs/daemon_split_plan.md` Phase 2.

### #5 — Permission decisions in the audit chain

`PermissionPolicy.check()` decides allow/deny/prompt without writing
to the hash-chained audit log. Today `_audit()` is called from a few
specific tool sites, not from the policy decision point.

**Why deferred:** the right shape is an injected `audit_sink` on the
policy object — but `PermissionPolicy` is instantiated very early
(before `_audit`'s layout dependency is bound), so the wiring needs
careful nullability handling and a redaction pass for prompt content.
M effort that's better as its own pass. The current `_audit()` calls
from `_common._audit` already cover the most common tool-invocation
sites; the gap is the policy-decision audit specifically, which
matters more once hardware-tier confirmations start firing. Tracked
as an 0.1.x correctness follow-up.

### #10 — `main.py` tool wrappers move to per-category modules

The 66 inline `@register_tool_from_function` wrappers in `_register_builtins`
mix registration, permission tiers, prompt-facing docstrings, and
`_pipeline` access. The `reload_skills` `NameError` was a symptom.

**Why deferred:** correct direction but big refactor — moves
~1200 lines across ~15 files, and a wrapper move means re-grepping
every test that imports a wrapper. Better as a focused PR after the
voice/Kokoro work lands, when no other large diffs are competing for
the same files. Tracked as 0.2.0 cleanup.

### #12 — Split `_dispatch_one_tool` along testable boundaries

The single method handles name normalization, dispatch-map lookup,
backstop counts, progress callbacks, guardrail hooks, permission
error typing, execution, result truncation, failure-signature
accounting, and transcript mutation. Future policy changes risk
unintended interactions.

**Why deferred:** the right refactor (resolve / execute / classify /
postprocess / append), but the per-agent dispatch map (#3) just
landed in this same function — let it bake against the bench before
slicing it apart. Worth doing once we have data on the new dispatch
path's behavior. Tracked alongside #10.

---

# Code review (2026-05-25) — third review batch (Hermes integration)

A third review of the broader Hermes-style agent loop produced 8
findings spanning daemon transport, context compression, parser
structure, oversized results, MCP OAuth, background notifications,
parser registry, and config diagnostics. Disposition:

## Applied this round

| # | Finding | Fix |
|---|---|---|
| 3 | Oversized tool results were truncated to a preview, full body lost | `ContextGuard.truncate_oversized_result` now writes the full body to `<instance>/logs/tool_results/<ts>_<id>.{json,txt}` and the in-prompt marker carries the on-disk path. Best-effort: a write hiccup falls back to preview-only. `build_jaeger_agent` accepts an `artifact_dir` param; `main.py` wires `layout.logs_dir / "tool_results"`. 4 new tests pin the persistence path + the fall-back. |
| 6 | Background tasks finished silently; agent only learned via polling | At-most-once completion queue. `_refresh_status` stamps `notified=False` on the running→terminal transition; `consume_pending_completions(layout)` drains + marks them notified. New `pending_background()` tool returns `{completions: [...], count: N}`. Added to `background` toolset. 5 tests in `test_background_notifications.py`. |
| 8 | `--doctor` checked only deps, not the configured instance | New `check_instance(layout)` extends environment checks with config.yaml parse, `model.path` existence, ctx sanity, and logs/ writability. `main.py` resolves the default (or `--instance`) layout and runs the deeper check when a config exists. 5 new tests in `test_preflight.py`. |

## Deferred — with explicit reasoning

### #1 — Daemon streaming protocol / `attach` client

The Phase 1 daemon ships an NDJSON-over-UDS protocol but no real
streaming client; `jaeger attach` is a thin REPL today.

**Why deferred:** this is **Phase 2** of the daemon split (committed
in `docs/daemon_split_plan.md`). The Phase 2 work moves the agent
INTO the daemon, which lets the attach client become a real
streaming subscriber. Doing the client first would mean a second
rewrite once the agent moves. Tracked as Phase 2.

### #2 — Long-running context compression (history summarisation)

`ContextGuard.trim_to_fit` drops oldest groups when the prompt won't
fit. A compression pass (summarise dropped history into a single
"context so far" block) would preserve more signal at the same token
cost.

**Why deferred:** L-effort feature. Needs a summariser model
selection (local vs. delegated), a cache strategy so we don't pay
the summariser cost every turn, careful trim-vs-summarise picking,
and bench discipline so the compression doesn't quietly regress
routing. Group-aware trim covers the worst overflow case today.
Tracked for 0.2.0.

### #4 — Tool-guardrail controller (richer no-progress detection)

Already deferred in the first review (see #4 above). Third review
re-raised the same item; disposition unchanged.

### #5 — MCP OAuth flow for cloud-hosted servers

Local MCP servers are configured statically; cloud-hosted ones
require an OAuth dance that the framework doesn't yet model.

**Why deferred:** Hardware-integration track. The Jaeger port aims
at embodied work first; the MCP cloud surface is a deferred dependency
for that path. Tracked alongside the Jaeger port direction memo.

### #7 — Parser registry refactor

`drift_parser.py` now dispatches across five dialects (Gemma,
Qwen3-Coder XML, Hermes JSON envelope, Llama raw-JSON, Mistral
`[TOOL_CALLS]`). A registry table — `{dialect_name: probe_fn}` —
would be cleaner than the current sequential `if` cascade.

**Why deferred:** pure refactor with no behaviour change. The
dialect set is settling (Llama + Mistral just landed); refactoring
now risks churn the next dialect would invalidate. Worth doing when
the dialect set is stable, with tests pinning each branch first.
Tracked as 0.2.0 cleanup.
