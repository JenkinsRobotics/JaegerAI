# Changelog

JROS follows pragmatic semver — major.minor.patch — with the
understanding that pre-1.0 minor bumps may carry breaking changes.

## `0.2.0` — unreleased

Development branch open at `0.2.0`. See
[docs/ROADMAP_0.2.0.md](docs/ROADMAP_0.2.0.md) for the working
slate. Theme: refinement + Jaeger-port enablement; not a major
reshape. The 0.2.0 acceptance bar is "0.1.0 bench numbers held
or improved on every suite."

### Planned (highest-leverage)

- Flip the lean tool surface to default-ON (was opt-in via
  `JAEGER_TOOLSET_SCOPING=1`).
- `requires_toolsets` metadata drives `skill(view)` auto-load.
- Auto-generated `docs/agent_contract.md` from `rules.py`.
- `--doctor-deep` live API + model-load probes.
- Three Laws + safeguard hardening (gating item before the
  Jaeger physical-port).
- `.app` bundling with py2app for Launchpad.
- macos_computer per-app AppleScript dispatch expansion.

---

## `0.1.0` — 2026-05-25

The first coherent release of JROS — local-first agentic agent
framework. Squashed onto `master` from the 22-commit
`jaeger-os-hermes` branch. The pre-existing JROS concept import
(`c5143fb`) was deliberately overwritten; the hardware project
skeleton returns deliberately alongside unit bring-up.

**Bench result at release:** 46/51 = 90% pass on the flat corpus,
every suite above its advisory threshold; routing 24/25 = 96%
on gemma-4-E4B-it, hermetic-verified. 1160 tests pass
(`scripts/run_tests.sh`); smoke tier in 1.4s, full in 22s.

### Added — agent core

- Framework-free Phase-9 `JaegerAgent` loop replaces pydantic-ai.
  Talks to OpenAI / Anthropic SDKs and in-process
  `llama_cpp.Llama` directly.
- Multi-dialect drift parser (Gemma × 3, Qwen3-Coder XML, Hermes
  JSON envelope, Llama `<|python_tag|>`, Mistral `[TOOL_CALLS]`)
  with explicit alias table for known renames.
- Pre-flight `ContextGuard` — group-aware trim that keeps assistant
  `tool_calls` paired with matching `tool` results; oversized
  results persist to `<instance>/logs/tool_results/` with the
  in-prompt body kept as a preview.
- Tier-based permission policy (READ_ONLY / WRITE_LOCAL /
  EXTERNAL_EFFECT / HARDWARE / PRIVILEGED / DEV_BYPASS) with
  the Three Laws block wrapping every system prompt.

### Added — prompts (Core / Safety / Instance split)

- `core/prompts/rules.py` for static behavioural strings;
  `core/prompts/context_blocks.py` for dynamic blocks;
  `core/prompts/assemble.py` as the single
  `assemble_prompt(layout, *, mode)` entry (modes:
  `agent` / `subagent` / `deep_think` / `idle_board` / `cron`).
- `core/prompts/synthetic.py` consolidates every framework-
  injected user message (idle-board pickup, Deep Think directive,
  cron frame).

### Added — tools + registry

- `ToolDef` carries registry metadata: `toolset`,
  `permission_tier`, `side_effect`, `max_result_chars`,
  `check_fn`, `requires_env`, `examples`; `is_available()`
  surfaces runtime preconditions.
- Plugin readiness → tool visibility — `text_to_speech` /
  `listen` / `send_message` / `browser` / MCP tools hide
  themselves when their backing plugin's libs / creds aren't
  ready.
- Lean tool surface — CORE slimmed to umbrella tools (`memory`,
  `kanban`); granular siblings moved to loadable toolsets.
  Opt-in via `JAEGER_TOOLSET_SCOPING=1` (default-ON planned for
  0.2.0).
- `describe_tool` returns tier / availability / toolset /
  examples / `requires_env` in addition to the schema.

### Added — skills

- Skill loader requires `tests/smoke_test.py` for non-core code
  skills.
- Plugin manifest schema (Pydantic `PluginManifest`) +
  `audit_plugin_dir` validation in `--doctor`.
- `skill(action="list")` paginates with `limit` / `offset` /
  `category` filtering and category counts always returned.
- Two computer-use skills:
  - `computer_use_v1` — universal screenshot path (cross-OS).
  - `macos_computer_v1` — Mac-recommended **capability ladder**
    (AppleScript → browser CDP → Accessibility → vision
    fallback). 3 model-visible tools (`computer_do` /
    `computer_use` / `computer_look`); focus-preserving;
    10-30× faster than the screenshot loop where applicable.

### Added — kanban / Deep Think

- Board autonomy — idle-tick worker picks up `backlog` /
  `ready` / `in_progress` cards. `board_digest` block injected
  into the system prompt so the agent SEES what's actionable.
- `kanban` umbrella tool with `kind=general|deepthink` —
  deepthink cards swap to the coder model after user approval.

### Added — TUI / daemon / tray

- Hermes-style TUI — banner, turn rules, answer box, status bar,
  slash commands; 24-bit hex accent for cross-terminal
  consistency.
- Daemon: `jaeger {start | stop | status | restart | tray | bench}`,
  NDJSON over Unix-domain socket (Phase-1; agent moves into the
  daemon in 0.2/0.3).
- Menu-bar tray with PNG icons (running / off variants); J
  silhouette derived from a Lilith disc, full-colour when up,
  desaturated when down. Dock icon hidden via
  `NSApplicationActivationPolicyAccessory`. Tray singleton; full
  Quit teardown kills daemon + every tray.
- TUI singleton via per-instance run-dir PID file.

### Added — diagnostics

- `--doctor` extends to instance-aware checks: `config.yaml`
  parse, `model.path`, ctx sanity, daemon health, memory JSON
  integrity, plugin manifests, skills health, tool registry
  resolution. `--doctor-json` + `--doctor-check` modes.
- `system_health(deep=False)` agent tool — 8 fast substrate
  probes (<3s). `deep=True` adds three live-agent-loop turns.

### Added — bench

- Agent-callable `run_benchmark` tool. **Hermetic memory
  snapshot/restore** — bench writes can't pollute live state.
- Flat 51-case corpus (routing / multistep / multiturn /
  recovery / files / memory / web / code / audio / schedule)
  with per-suite advisory thresholds.
- Bench-scope permission context auto-approves sandboxed
  WRITE_LOCAL so confirm-gated tools don't prompt per case.
- `jaeger bench run` / `jaeger bench timing` CLI verbs.

### Added — tests

- 1160 passing, marker-tiered (smoke / integration / model /
  ui / subprocess / slow / regression).
- `scripts/run_tests.sh` pins TZ / LANG / PYTHONHASHSEED, strips
  auth env vars by pattern, runs `pytest-xdist` workers.

### Removed / superseded

- Pre-existing `c5143fb 0.1 Imported  Jros Concept` on origin/
  master overwritten by the 0.1.0 squash. The hardware project
  directories (`01_DESIGN` through `08_RELEASES`) and the old
  root-level `agent_doctor.py` / `main.py` / `model_resolver.py`
  / pre-refactor `benchmark/*.md` files were superseded by the
  full `src/jaeger_os/` package shipped here. The embodied
  unit's hardware skeleton will be added back deliberately in a
  future release alongside unit bring-up.
- `computer_use_v2` skill retired in favour of the
  capability-ladder `macos_computer_v1`. AX bits salvaged into
  the new skill's `ax_engine.py`.

---

## Pre-history — see Alpha 0.1 through Alpha 20

The `jaeger-os-hermes` branch (squashed into the 0.1.0 commit)
carried 22 incremental commits from `Alpha 0.1` through
`Alpha 20`. That branch was deleted at release time; commits
remain reachable in the local reflog (~90 days) and via SHA if
audit is ever needed.

