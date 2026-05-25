# Changelog

JROS follows pragmatic semver — major.minor.patch — with the
understanding that pre-1.0 minor bumps may carry breaking changes.

## `0.1.0` — 2026-05-24

First versioned baseline. The agent + tool layer is feature-complete
and bench'd; the hardware-node layer (transport, motors, LEDs) is the
roadmap. Verified L1 routing: **gemma-4-26B-A4B-it 97.1%** on 34
single-turn prompts (`benchmark/levels/history/BENCHMARK_v0.1.0_baseline.md`).

### Added

- **Daemon scaffold + macOS tray** — `jaeger start | stop | status | restart`
  lifecycle, Unix-domain socket protocol, lifecycle CLI, and rumps-based
  tray that polls daemon state and exposes Start/Stop/Restart/Open TUI.
  Agent still lives in the TUI process; **Phase 2 (move agent into
  daemon) is the next track** — see [docs/daemon_split_plan.md](docs/daemon_split_plan.md).
- **Pre-flight context guardrail** — refuses to send a turn that won't
  fit the loaded ctx window, trims oldest history (group-aware so
  assistant `tool_calls` + matching tool results drop atomically), and
  surfaces a typed `ContextOverflow` with budget breakdown when even
  max trim can't fit. Per-tool-result truncator caps oversized payloads
  before they land in history. See [docs/context_guard.md](docs/context_guard.md).
- **Lean tool surface infrastructure** — `describe_tool(name)` meta-tool
  to peek at any registered tool's schema; system-prompt tool catalog;
  `load_toolset(name)` widens the active set mid-session. **Opt-in via
  `JAEGER_TOOLSET_SCOPING=1`**; default OFF for routing-accuracy
  reasons. See [docs/lean_surface.md](docs/lean_surface.md).
- **Kanban grid view** — `/board` now renders the 5-column kanban as
  a Rich `Columns` of `Panel`s (was a vertical list).
- **`remote_terminal` (SSH outbound) tool** — Tier-4 wrapper around the
  local `ssh` binary with `BatchMode=yes`, `ConnectTimeout=10`, and
  `StrictHostKeyChecking=accept-new` pinned. Inbound covered by plain
  sshd + tmux. See [docs/remote_access.md](docs/remote_access.md).
- **Three Laws prepended to every system prompt** via
  `with_three_laws()` in `core.safety.safety_rules` — the safety
  contract is the first block the model reads.
- **Typed safety errors** — `error_type` + `retryable` + optional
  `required_tier` on tool-result dicts when the dispatch raises
  `PermissionDenied` / `ConfirmationRequired` / `HumanOverrideRequired`.
  The model can now distinguish "retry with different args" from
  "user said no — don't try again".
- **Tool-name normalization at the loop boundary** — `normalize_tool_name`
  (alias/case/separator/suffix) runs once before `has_tool` check.
  Catches `ReadFileTool` → `read_file`-style drift.
- **Skip-final multi-step intent suppression** — `_looks_multistep()`
  heuristic blocks the skip-final short-circuit when the user prompt
  has chaining markers ("and then", "first ... then", numbered lists).
- **TUI status-bar fixes** — loaded ctx (from `client.loaded_ctx`)
  instead of just config ctx; `/runtime` surfaces "model trained for
  up to N tokens — bump config.model.ctx" when loaded < native; the
  0%-gauge bug (estimator only walked legacy `msg.parts[].content`,
  missing the Phase-9 dict shape) is fixed.
- **Drift parser — loose `<function=…>` form** — Qwen3-Coder sometimes
  emits the Qwen XML without the outer `<tool_call>` wrapper. Now
  salvaged. Was leaking tool-call XML into chat text.
- **Latency telemetry** — `tool_time` and `loop_time` populate
  `LatencyReport` (were both 0.0).
- **Bench infrastructure** — `benchmark/run_model_sweep.py` drives
  multi-model comparisons; YAML-aware config-swap; multi-level row
  parser handles L1/L2/L3/L4 formats. Scorer in `level1_routing.py`
  accepts umbrella-form tools (`memory` for the 5 fine-grained
  memory verbs, `execute_code` for `run_python`).

### Changed

- **Lean tool surface default — ON → OFF.** Briefly defaulted ON after
  the lean surface infrastructure landed, then reverted after the
  0.1.0 bench showed routing regressions on Gemma 4 (default −6 pts,
  E2B −18 pts). Stays opt-in until *auto-load-on-intent* eliminates
  the meta-step.
- `last_halt_reason` is now consistently set to `"interrupted"` on
  AgentInterrupted at both interrupt sites (was empty assistant
  message at one site, "the turn was interrupted" at the other).
- `JaegerAgent.__init__` now distinguishes `self._all_tools` (full
  registered set, used for dispatch + validation + `describe_tool`)
  from `self.tools` (the model-visible subset, computed per access
  through `tool_visible()` when scoping is on).

### Fixed

- `reset_read_tracker()` is now called at the top of every `run_turn`.
  The file-read dedupe state was leaking across turns, causing
  legitimate next-turn reads to return unchanged stubs.
- Context-window error message (`cloud_errors.friendly_error_text`)
  now has a proactive companion (`friendly_overflow_text`) that fires
  *before* the server bites, with exact token-budget breakdown.

### Deprecated / removed

- The legacy pydantic-ai message shape (`msg.parts[].content`) is no
  longer the primary path — the Phase-9 dict shape is canonical. Code
  that walks history still accepts both shapes for backwards compat
  in mixed sessions.

### Bench

- **L1 (single-turn routing) baselined** — see
  `benchmark/levels/history/BENCHMARK_v0.1.0_baseline.md`. Top tier:

  | Model | Route % | p50 | Notes |
  |---|---|---|---|
  | gemma-4-E4B-it-Q4_K_M | 97.1% | 1.6s | 5.3 GB — strong candidate to replace the default |
  | gemma-4-26B-A4B-it-Q4_K_M | 97.1% | 3.0s | current JROS default |
  | gemma-4-E2B-it-Q4_K_M | 94.1% | 1.2s | smallest viable |
  | Qwen3-Coder-30B-A3B | 94.1% | 3.2s | code-tuned (Deep Think) |
  | Qwen3.5-9B | 88.2% | 35.1s | obsolete vs E2B |

  Not viable: Gemma 3 (no tool calls), Llama-3.2-3B (no tool calls),
  Ministral-14B (no tool calls), Qwen3.6-27B-Dense (timeout),
  Qwen3.6-35B-A3B (load failure mode under cold subprocess —
  separate bug, not a code regression).

- **L2 / L3 / L4** still need re-runs against the umbrella-aware
  scorer (the `_UMBRELLA_EQUIVALENTS` map currently lives in L1 only;
  L2/3/4 modules need the same update). Tracked as 0.1.x follow-up.

### Up next (post-0.1.0)

- **Hardware integration begins** — JP01 transport, motors, LEDs,
  capability-gated skill loader on physical nodes.
- Daemon-split Phase 2: agent moves into the daemon process.
- L2/L3/L4 bench coverage with the umbrella-aware scorer.
- Tool guardrail controller (review finding #4) and safe parallel
  tool execution (review finding #5) — both deferred from 0.1.0;
  reasoning in [docs/code_review_2026_05_24.md](docs/code_review_2026_05_24.md).
