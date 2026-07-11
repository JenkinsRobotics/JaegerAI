# Hermes vs. JROS — Tool & Skill Integration Audit

**Date:** 2026-05-21
**Scope:** How tools and skills wire into the agent loop in JROS (Jaeger-OS)
versus hermes-agent. Verified by reading source in both trees — no assumptions.

> ## ⏩ Port progress (2026-05-21)
>
> **Done (8 of 12):**
> - **#1** tier gating — `@requires_tier` on every write/effect tool +
>   read-anywhere file tools (`core/tools/_common._resolve_read`).
> - **#2** skill safety guard — `core/skills_guard.py`, wired into
>   `skill_loader` + the `skill` tool.
> - **#3** lazy-deps — `core/lazy_deps.py` + `SecurityConfig`.
> - **#4** usage telemetry — `core/usage_stats.py` (`logs/usage.json`).
>   *(Also fixed a dead import in `_run_via_iter` — `from .usage_stats`
>   should have been `from .core.usage_stats`; telemetry was silently
>   no-op'ing.)*
> - **#6** mid-tool interrupt — `core/tool_interrupt.py`: one shared
>   turn-interrupt Event (unified with `begin_turn_cancel_scope`) +
>   `run_interruptible` subprocess helper. Wired into `run_python` /
>   `run_shell` / `run_in_venv` (kill the child) and `web_fetch`
>   (chunked download, polls per chunk); preflight check in `look_at` /
>   `browser`.
> - **#8** skill provenance — `origin` field + `.origin` marker.
> - **#9** `scripts/` affordance — `skill(view, file=…)` + a `files` listing.
> - **#12** OSV malware check — `core/osv_check.py`, wired into `venv`.
>
> **Remaining (4) — loop-internal / large, do these next:**
> - **#5** tool-result formatter ladder — belongs in the `R4` main-loop
>   rebuild (`docs/main_loop_review.md`); the hallucination-prevention
>   logic in `_fast_finalize_sync` is load-bearing, don't rush it.
> - **#7** MCP OAuth + dynamic refresh — port `mcp_oauth_manager.py`.
> - **#10** central tool registry / per-tool metadata.
> - **#11** oversized-result persistence / turn budget.
>
> ~367 tests green. Start the next session on **#7** (self-contained) or
> **#5** as part of the main-loop rebuild.

**References read**
- hermes: `tools/registry.py`, `tools/__init__.py`, `tools/schema_sanitizer.py`,
  `tools/path_security.py`, `tools/file_tools.py` (skim), `tools/lazy_deps.py`,
  `tools/interrupt.py`, `tools/osv_check.py`, `tools/url_safety.py` (skim),
  `tools/clarify_gateway.py`, `tools/tool_result_storage.py`,
  `tools/tool_output_limits.py`, `tools/skills_tool.py`, `tools/skills_hub.py`
  (skim), `tools/skills_sync.py`, `tools/skills_guard.py`,
  `tools/skill_provenance.py`, `tools/skill_usage.py`, `toolsets.py` (skim),
  `toolset_distributions.py` (skim), `run_agent.py` (tool-exec paths),
  `cli.py` (tool-progress callbacks).
- JROS: every `core/tools/*.py`, `core/toolsets.py`, `core/registry.py`,
  `core/skill_loader.py`, `core/playbook_skills.py`, `core/skill_benchmark.py`,
  `core/skill_package.py`, `core/reflection.py`, `core/permissions.py`,
  `core/llm_model.py` (schema build), `main.py` (`_register_builtins`,
  `_get_agent`, `build_agent`, `_build_mcp_tools`, `_run_via_iter`,
  `_run_with_fix_loop`, `boot_for_tui`), `plugins/mcp/client.py`,
  `skills/` tree.

One structural fact frames everything below: **JROS runs the
[pydantic-ai](https://github.com/pydantic/pydantic-ai) `Agent` loop**
(`agent.iter()`), so a large amount of tool plumbing — schema generation
from typed signatures, dispatch, the tool-call/return message protocol,
typed-arg validation retries — is owned by the pydantic-ai library, not by
JROS code. Hermes hand-rolls the entire loop. So several rows below are
"MATCH (via pydantic-ai)" rather than "JROS reimplemented it."

---

## Part A — Tool pipeline

| Concern | Hermes | JROS | Status | Note |
|---|---|---|---|---|
| Tool registration & schema generation | Self-registering modules call `registry.register(name, toolset, schema, handler, check_fn, requires_env, …)` at import; `discover_builtin_tools()` AST-scans `tools/*.py` for a top-level `registry.register` call and imports those. Schemas are hand-written OpenAI-format dicts. | `_register_builtins()` in `main.py` decorates ~60 closures with `@agent.tool_plain`; pydantic-ai builds the JSON schema from the typed signature + docstring. Code skills add more via `register(agent)`. | MATCH | Different mechanism, same outcome. JROS schema-from-signature is *less* error-prone than hand-written dicts but gives no central registry object — there is no `ToolEntry`, no per-tool metadata (emoji, `requires_env`, `max_result_size_chars`, `check_fn`). |
| Tool-call dispatch | `registry.dispatch(name, args)` looks up the entry, bridges async via `_run_async`, wraps all exceptions into `{"error": …}`. | pydantic-ai's `CallToolsNode` dispatches; `_run_via_iter` only *observes* the node stream. | MATCH | pydantic-ai owns it. |
| **Tool result formatting / how results feed back to the model** | Tool handlers return JSON strings. Result is appended to messages as a `tool` role message **verbatim** (the model sees the raw JSON), then size-managed (see budget rows). `cli.py` renders a separate human-facing "cute message" + inline edit diff. | Tool returns a Python `dict`; pydantic-ai serializes it into a `ToolReturnPart` the model sees on the next request. **Plus** a JROS-specific layer: `SKIP_FINAL_TOOLS` / `_DETERMINISTIC_FINAL_TOOLS` short-circuit the loop after one tool call, and `_fast_finalize_sync` runs a bounded LLM call (or `_format_tool_result_as_answer`, a 130-line hand-written per-tool string renderer) to paraphrase the result. | WEAKER | JROS's `_format_tool_result_as_answer` is a giant `if name == …` ladder — every new tool that wants a clean skip-final answer needs a new branch. Hermes feeds raw JSON to the model and lets the model phrase the answer; JROS's skip-final path is a latency optimization that creates a parallel formatting surface that drifts from the tool set. |
| Tool error handling & retry | `dispatch` catches every exception → `{"error": …}`; `_detect_tool_failure` classifies; failed tool results stay in the transcript so the model can react. No automatic re-run of the same call. | pydantic-ai retries **typed-arg validation** failures (`Agent(retries=2)`). JROS adds `_run_with_fix_loop`: one extra pass that detects a failed `execute_code` / a `syntax_ok:false` write and re-prompts "read the file, fix it, re-run." `_semantic_failure_signature` + `_loop_halt_reason` halt a turn after `_MAX_SEMANTIC_FAILURES` repeats of the same error. | MATCH | Roughly equal, different emphasis. JROS's run-and-fix loop is actually *stronger* for the code-writing case; hermes leans on the model. |
| Tool timeouts | Per-tool: `terminal_tool` / `code_execution_tool` carry their own subprocess timeouts; budget config has size caps not time caps. No global per-tool-call wall clock. | Per-tool: `run_python` 10s, `run_shell`/`run_in_venv` capped, MCP `call()` 60s. No global per-tool-call wall clock either; the turn-level `_MAX_TOOL_CALLS=24` backstop bounds the *turn*. | MATCH | Both rely on per-tool timeouts; neither has a uniform per-call deadline. |
| Permission / tier gating | `approval.py` (58 KB) — a full approval engine: per-tool approval prompts, allowlist/denylist, `tirith_security.py` policy, `website_policy.py`, OSV malware checks on package installs. Approval is plumbed through `run_agent` before dispatch. | `core/permissions.py` — clean 6-tier model (`requires_tier` decorator, `PermissionPolicy`, one-way-door safe modes, per-skill `PermissionGrants` persisted to `permissions.json`). **But only ~10 of ~60 builtin tools carry a `@requires_tier`** — `get_time`, `calculate`, `read_file`, `list_skill_dir`, `search_files`, `run_shell`, `install_package`, `run_in_venv`, `start_background`, `stop_background`, `recall`, `list_facts`, `system_status`. `write_file`, `patch`, `delete_file`, `browser`, `open_on_host`, `send_message`, `download_model`, `text_to_speech`, `image_generate` and the skill-authored tools are **ungated**. | WEAKER | The tier *machinery* is arguably cleaner than hermes's. The *coverage* is the gap — the docstrings claim "PRIVILEGED tier" for `download_model` / `terminal` but `terminal`→`run_shell` is gated while `download_model` and all file *writes* are not. A write or a browser action never prompts. |
| Path security & sandboxing (file/terminal tools) | `path_security.validate_within_dir` + `has_traversal_component`, reused across skill/cron/credential tools. Terminal tool runs in the chosen environment backend (local/Docker/SSH/Modal/Daytona) — sandbox strength is the *environment*. | `_common._resolve_under` — rejects absolute paths, `..`, symlink escape; file writes are hard-confined to `<instance>/skills/`. `run_python` uses `python -s -E` in the workspace; `run_shell` runs in a fresh tempdir but is explicitly *not* filesystem-confined (documented). No pluggable environment backend. | MATCH | JROS sandboxing is solid for file tools and *tighter by default* than hermes for the local case. Hermes wins only on the multi-backend environment abstraction (Docker/Modal/etc.), which JROS doesn't need. |
| Lazy dependency loading | `lazy_deps.py` — `LAZY_DEPS` allowlist of pip specs per feature (`tts.elevenlabs`, `search.exa`, `platform.discord`, …); `ensure("feature")` venv-installs on first import, gated by `security.allow_lazy_installs`, surfaces `FeatureUnavailable` with remediation. | None. `install_package` exists as an *agent tool* (the model decides to install), and tool files do `try: import requests` with manual fallbacks. There is no framework-level "feature needs package X, install it transparently" path. | MISSING | JROS optional backends (Kokoro, Moondream, SDXL, ddgs) either are hard deps or fail at runtime with an import error the model has to interpret. There is no curated allowlist of installable feature deps. |
| MCP tool integration | `mcp_tool.py` (140 KB) + `mcp_oauth.py` + `mcp_oauth_manager.py`: full client, OAuth flows, dynamic `tools/list_changed` refresh (registry `deregister`/re-register), per-server toolsets, OSV scan on MCP-suggested installs. `mcp_serve.py` also exposes hermes itself as an MCP server. | `plugins/mcp/client.py` (~210 lines): connect to servers from `mcp_config.json`, list tools, `call_mcp_tool` with a 60s timeout. `_build_mcp_tools` wraps each via `Tool.from_schema`; opt-in (`--with-mcp` / `JAEGER_WITH_MCP=1`). | WEAKER | JROS MCP is functional read/call. Missing: OAuth (so no Gmail/Drive/Calendar-style authenticated servers), dynamic tool-list refresh, and JROS being usable *as* an MCP server. Static config only. |
| Live tool-progress callbacks | `tool_progress_callback("tool.started"/"tool.completed", name, preview, args, duration, is_error)`; `_on_tool_gen_start` (streaming-args preview), `_on_tool_start` (edit snapshot capture), `_on_tool_complete` (inline diff render). Drives spinner, scrollback, voice beeps. | `_run_via_iter` emits via `_pipeline["tool_event_cb"]`: `("start"/"done", name, detail, elapsed)` from `CallToolsNode` / `ModelRequestNode` walking. TUI renders the `┊` activity lines. | MATCH | JROS covers start/done + elapsed. Missing the *args-streaming* preview ("preparing write_file…" while a 45 KB payload streams) and the before/after edit-diff render — JROS's callback fires only on whole-call boundaries. |
| Tool-usage tracking | `skill_usage.py` tracks per-skill view/use counts in a sidecar `.usage.json` (used by the Curator). Tool calls themselves are logged to agent.log + the persistent error log. | Every tool effect is appended to `logs/audit.log` via `_audit` (sandbox ops, `run_shell`, denials). Turn logs via `write_log`. No per-tool or per-skill *call counter*. | WEAKER | JROS has a strong audit *trail* (tamper-evident, every op) but no usage *telemetry* — nothing answers "which tools/skills get used, how often, how often they fail." |
| Interrupt / cancel mid-tool | `tools/interrupt.py` — **per-thread** interrupt set; tools poll `is_interrupted()` and bail out mid-execution (critical for the concurrent gateway). `_ThreadAwareEventProxy` shim for legacy call sites. | `_run_via_iter` checks `_pipeline["cancel_event"]` (a `threading.Event` the TUI sets) **between nodes** of the agent loop. | WEAKER | JROS can interrupt *between* tool calls but not *during* one — a running `run_shell` / `web_fetch` / `browser` action finishes before the cancel is honored. Hermes tools cooperatively check mid-call. |

---

## Part B — Skill pipeline

| Concern | Hermes | JROS | Status | Note |
|---|---|---|---|---|
| Skill discovery (playbook vs code) | Skills are SKILL.md playbooks under `~/.hermes/skills/` + bundled `skills/`. `skills_tool._find_all_skills` parses frontmatter, category-from-path, tags, platform filter, disabled-set. Progressive disclosure: `skills_list` returns name+description only. | **Two separate systems.** `playbook_skills.py` discovers SKILL.md files (frontmatter, category, tags) → surfaced by the `skill()` tool. `skill_loader.py` discovers `*_v<N>/` folders with a Python module → registers tools onto the agent. `_is_code_skill()` keeps the two from overlapping. There is also `core/registry.py` (a third, manifest.yaml-based discovery for `cognitive`/`physical` skills) that nothing in the live path appears to call. | WEAKER | The split is deliberate and documented, but JROS has *three* skill-discovery code paths (`playbook_skills`, `skill_loader`, `registry`) with three different on-disk conventions (`SKILL.md` frontmatter, `_vN` folder + `register()`, `manifest.yaml`). Hermes has one. `registry.py` looks dead — only ~2 code skills exist (`computer_use_v1/v2`) and the 89 SKILL.md files are all playbooks. |
| Skill loading (smoke tests, registration) | Skills are content, not code — "loading" = copying bundled→user dir via `skills_sync.py` with a hash manifest. No smoke test; `skills_guard.py` static-scans externally-sourced skills before install. | `skill_loader.load_and_register`: discovers `*_vN` folders, runs `tests/smoke_test.py` as a subprocess gate (fail → skipped + audited), imports the module, calls `register(agent)` through `_ToolCapturingAgent` to capture which tools it added. Idempotent via `_REGISTERED_KEYS`. | MATCH | Different by design — JROS code skills *are* executable so they need a smoke gate; hermes skills are playbooks so they need a malware *scan* instead. JROS has the gate, hermes has the scan. Neither has both. |
| How a skill's tools/instructions surface to the model | `skill_view` returns full SKILL.md + linked-file listing on demand (progressive disclosure). Skill-suggested tools are normal registered tools. | Playbook skill: the `skill()` tool (`list`/`search`/`view`) — model discovers and reads on demand, capped at 16 KB. Code skill: its `register()`-added tools appear in the schema; the loader also calls `register_skill_toolset` so the skill becomes a loadable toolset. | MATCH | Both do progressive disclosure well. JROS's `skill` tool mirrors hermes's `skills_list`/`skill_view` closely. |
| Skill execution (embedded scripts / `scripts/` dir) | `skill_view(name, "scripts/foo.py")` reads a script file; the model then runs it with the terminal tool. `scripts/` is a recognized linked-file category. | The `skill()` tool returns `instructions` + the skill's `folder` path; the model is told to run embedded shell/Python with `terminal`/`execute_code`. No special handling of a `scripts/` subdir — the model must `read_file` then run. | WEAKER | JROS playbooks can carry scripts, but there is no first-class "here are this skill's scripts" affordance — `skill view` returns only SKILL.md text (16 KB cap), not a manifest of the skill's `scripts/`/`references/`/`assets/` files the way hermes's `skill_view` does. The model has to guess filenames. |
| Skill provenance & trust | `skill_provenance.py` — a ContextVar marking whether a skill write came from the background-review fork vs. a foreground user request, so the Curator only auto-manages skills it created. `skills_hub` `HubLockFile` tracks install source. `skills_guard` trust levels (builtin/trusted/community). | None. A code skill's `zone` is `core` vs `instance`; that's the only provenance. `package_skill` writes an author field + `package_sha256` into the bundle manifest. No trust level, no record of where an installed skill came from, no agent-vs-user authorship marker. | MISSING | Nothing distinguishes a skill the agent wrote itself from one the user wrote from one pulled off the internet. The `package_sha256` exists but nothing verifies it on the (not-yet-built) install side. |
| Skill usage tracking | `skill_usage.py` — per-skill view/use counters, lifecycle states (active/stale/archived), feeds the Curator's prune/archive decisions. | None. The `skill()` tool does not bump a counter; no per-skill telemetry. | MISSING | No data to drive any future "this skill is stale / unused" cleanup. |
| Skill marketplace / install / sync | `skills_hub.py` (3261 lines) — multiple sources (GitHub, skills.sh, ClawHub, Claude marketplace, LobeHub, well-known URLs), quarantine→scan→install, `skills_sync.py` bundled-skill seeding with hash manifest, update detection. | `skill_package.py` packages an instance skill into a `.zip` + `skill_manifest.json`. `skill_market.py` exposes `package_skill` / `benchmark_skill` tools. **`submit_skill` / `search_skill` / `install_skill` are explicitly deferred** — "the marketplace repo doesn't exist yet" (`docs/marketplace_spec.md`). No sync of bundled skills into the instance dir. | WEAKER | JROS has the *packaging* half. The *distribution* half (search/install/update/quarantine/scan) is entirely absent. Bundled skills also aren't synced into `<instance>/skills/`, so the agent can't version-bump a shipped skill. |
| Skill benchmarking | None — hermes has no per-skill scored benchmark. | `skill_benchmark.py` + the `benchmark_skill` tool: runs a skill's `tests/benchmark.py`, parses one JSON `{score,passed,total}`, appends to `benchmark_history.jsonl`, reports `delta` vs. the previous run. | **JROS-ONLY (better)** | This is a genuine JROS strength — see Part D. |
| Skill hot-reload | N/A — playbooks are re-read from disk each `skill_view`, so a playbook edit is "live" with no reload. | Playbooks: same — `discover_playbooks()` re-scans on every `skill()` call, so a SKILL.md edit is live. Code skills: the `reload_skills` tool re-runs `load_and_register`; `_REGISTERED_KEYS` prevents double-registration, but **a *changed* skill at the same `(name, version, zone)` will NOT re-register** — the agent must bump `_vN`. | MATCH | Playbook hot-reload matches. Code-skill "reload" only picks up *new* skills/versions, not edits to an existing version — but that is intentional (pydantic-ai raises on duplicate tool names; versioning is the override mechanism). |
| Skill safety guard | `skills_guard.py` (932 lines) — regex static-analysis scanner for exfiltration, prompt injection, destructive commands, persistence; trust-aware install policy (community findings = blocked unless `--force`). | None for *playbook* skills. Code skills get a `smoke_test.py` subprocess gate (functional, not security). No static scan of skill content for malicious patterns. | MISSING | A playbook skill (89 of them ship; some are red-teaming/godmode content) is markdown the model is told to *execute via `terminal`*. Nothing scans that markdown. An installed-from-marketplace skill (when that ships) would have no guard at all. |

---

## Part C — Missing pipelines & nuances, ranked

Ranked by impact on the agent actually getting tasks done.

### 1. Tier gating covers only ~1/6 of the tool surface
**What:** `core/permissions.py` is a clean 6-tier system with a `requires_tier`
decorator, but only ~10 of ~60 builtin tools wear it. `write_file`, `patch`,
`delete_file`, `download_model`, `browser`, `open_on_host`, `send_message`,
`image_generate`, `text_to_speech`, and *every skill-authored tool* are
ungated. **Why it matters:** the docstrings actively lie — `download_model`
says "PRIVILEGED tier — routes through confirmation," `browser` drives a real
browser, `send_message` posts to Discord/Telegram, and none of them prompt.
The safety story (MEMORY: "Three Laws + safeguard hardening must land before
the Jaeger port") rests on this decorator, and it is mostly not applied. A
robot embodiment with ungated `open_on_host`/`browser`/`send_message` is the
exact failure mode the tier system exists to prevent.
**Port sketch:** This is mechanical, not architectural. In `main.py`
`_register_builtins`, add `@requires_tier(...)` to every write/effect tool:
`write_file`/`patch`/`append_file`/`delete_file` → `WRITE_LOCAL`;
`send_message`/`browser`/`open_on_host` → `EXTERNAL_EFFECT`;
`download_model` → `PRIVILEGED`. For skill-authored tools, have
`skill_loader._ToolCapturingAgent` reject (or default-tier) any captured tool
whose handler lacks `__lilith_permission__` — `permissions.get_tier()` already
exists for exactly this introspection. Add one test that asserts every
registered tool resolves to a tier.

### 2. No skill safety guard / content scan
**What:** Hermes's `skills_guard.py` static-scans skill content for
exfiltration, prompt injection, and destructive commands before install, with
trust levels. JROS has *zero* scanning of playbook skills — and 89 SKILL.md
files ship, including `red-teaming/godmode` whose body is markdown the model
is instructed to run via `terminal`/`execute_code`. **Why it matters:** a
playbook is executable-by-proxy. Today the only thing between a malicious
SKILL.md (whether shipped, user-written, or — once the marketplace lands —
downloaded) and `run_shell` is the model's judgment. When `install_skill`
ships, it will install unscanned code.
**Port sketch:** Port `skills_guard.py` as `core/skills_guard.py` — the
regex-pattern scanner is self-contained and dependency-free. Call
`scan_skill()` in two places: (a) `skill_loader.load_and_register` before
importing a code skill's module (alongside the smoke gate); (b) the future
`install_skill` path. Add a `trust` field to `PlaybookSkill`/`DiscoveredSkill`
(`builtin` for `core/`, `instance` for agent-written) and have the `skill`
tool surface a warning when `view`-ing a community-trust skill.

### 3. No lazy dependency loading
**What:** Hermes's `lazy_deps.py` keeps an allowlist of pip specs per optional
feature and venv-installs them transparently on first use, gated by config.
JROS has no equivalent — optional backends (Kokoro TTS, Moondream2, SDXL,
ddgs, whisper) are either hard deps or fail at import time. **Why it matters:**
when the model calls `text_to_speech` or `vision_analyze` on a fresh install
without the weights/libs, it gets a raw `ImportError` it has to interpret,
instead of the framework either installing the dep or returning a clean
"feature unavailable, run X" message. It also forces a heavy default install.
**Port sketch:** Add `core/lazy_deps.py` with a `LAZY_DEPS` allowlist keyed by
feature (`tts.kokoro`, `vision.moondream`, `search.ddgs`, …) mapping to pinned
pip specs, and an `ensure(feature)` that installs into the instance venv
(`core/venv.py` already has `install_into_venv`). Have `speak.py`,
`vision.py`, `web.py` call `ensure(...)` at the top of their first-use path
instead of bare `try/import`. Gate on a new `config.security.allow_lazy_installs`.

### 4. No tool/skill usage telemetry
**What:** Hermes tracks per-skill view/use counts (`skill_usage.py`) and tool
call outcomes; JROS logs an audit *trail* but keeps no *counters*. **Why it
matters:** there is no data to answer "which tools fail most," "which skills
are dead weight," or to drive the kind of self-improvement the project wants
(MEMORY: reflection / skills self-improve). The `benchmark_skill` delta only
fires when the agent deliberately runs it; passive usage data would tell the
agent *which* skills are worth benchmarking.
**Port sketch:** Add `core/skill_usage.py` — a sidecar `<instance>/skills/.usage.json`
(or a table in the existing memory store) with `{skill: {views, uses, last_used}}`.
Bump it in the `skill` tool (`view` action) and in `skill_loader` when a
code-skill tool is invoked. For tools, the cleanest hook is `_run_via_iter`'s
existing `_emit_tool("done", …)` path — it already has tool name + elapsed +
the failure-signature machinery; write a counter there. Surface it via a new
`skill_stats` / `tool_stats` read tool.

### 5. Tool-result feedback path is a hand-written formatter ladder
**What:** JROS's skip-final optimization routes tool results through
`_format_tool_result_as_answer` — a 130-line `if name == "get_time": … elif
name == "calculate": …` ladder — and `_DETERMINISTIC_FINAL_TOOLS`, a
hardcoded frozenset. Hermes feeds raw JSON to the model and lets it phrase the
answer. **Why it matters:** every new tool that wants a clean one-shot answer
needs a new branch in the ladder *and* an entry in the frozenset, or it
silently falls through to `str(result)` and the user sees a raw dict. This
formatter set drifts from the tool set — it is unmaintainable as the tool
count grows, and skill-authored tools can never participate.
**Port sketch:** Two options. (a) Minimal: give each tool an optional
`format_result` callable (mirrors hermes's `ToolEntry`), looked up by name,
defaulting to "let the LLM phrase it." (b) Better: drop the per-tool ladder
entirely and always run `_fast_finalize_sync` (it already exists and is
bounded to ~120 tokens) — the latency cost is small and the maintenance cost
drops to zero. Touch `main.py` `_format_tool_result_as_answer`,
`_DETERMINISTIC_FINAL_TOOLS`, `_fast_finalize_sync`.

### 6. No mid-tool interrupt — ✅ DONE (2026-05-21)
**What:** JROS checked the cancel event *between* agent-loop nodes; a
long-running `run_shell` / `web_fetch` / `browser` / `look_at` (vision model
load) could not be interrupted once started. Hermes tools cooperatively poll
`is_interrupted()`. **Why it mattered:** MEMORY flags AEC barge-in / "user
speaks mid-turn" as a live goal. The user could interrupt the *agent's
thinking* but not a 60-second shell command.

**Shipped:** `core/tool_interrupt.py`.
- One process-wide turn-interrupt `threading.Event` —
  `begin_turn_cancel_scope` now hands *that* object back as the turn's
  `cancel_event`, so the flag the TUI sets, the flag `_run_via_iter` checks
  between nodes, and the flag a tool polls mid-call are all one Event (no
  second source of truth). **Deviation from the port sketch:** the sketch
  said per-thread (like hermes). JROS serialises turns through `llm_lock`
  and pydantic-ai dispatches sync tools onto anonymous worker threads the
  loop never names — so a per-thread design has no clean thread to target.
  Process-wide is correct here: one user turn at a time, and cancelling it
  should stop its tools *and* its delegates' tools.
- `run_interruptible()` — a `subprocess.run` drop-in that polls every 0.2s
  and `terminate()`→`kill()`s the child on interrupt, raising
  `ToolInterrupted` with the partial output. Wired into `run_python`,
  `run_shell`, `run_in_venv` (each now returns `interrupted: True`).
- `web_fetch` rewritten as a chunked `stream=True` download that polls
  `is_interrupted()` per 16 KB chunk (+ a 5 MB raw-body cap).
- `look_at` and `browser` get a preflight `is_interrupted()` check — their
  inner calls (VLM load, a Playwright action) are atomic and can't be
  broken mid-flight, but they no longer *start* on an already-cancelled
  turn.
- `tests/jaeger_os/core/test_tool_interrupt.py` — 11 tests (signal
  contract, helper normal/timeout/interrupt, child-actually-killed, wired
  tools, scope unification).

### 7. MCP integration has no OAuth and no dynamic refresh
**What:** JROS MCP (`plugins/mcp/client.py`) does static-config connect + call
only. Hermes has `mcp_oauth.py` / `mcp_oauth_manager.py` (full OAuth) and
dynamic `tools/list_changed` handling. **Why it matters:** the most useful MCP
servers — Gmail, Google Drive, Google Calendar (all three are in this
environment's own deferred-tool list) — require OAuth. Without it, JROS can
only talk to unauthenticated/local MCP servers, which sharply limits what
"connect an MCP server" buys the agent.
**Port sketch:** Port `mcp_oauth_manager.py` into `plugins/mcp/` — it is a
fairly self-contained OAuth device/code-flow manager with token persistence.
Wire it into `_MCPClient.connect()` so a server config can declare `auth:
oauth` and the manager handles the flow + token refresh. Dynamic refresh is
lower priority: add a `tools/list_changed` listener that re-runs
`register_mcp_tools` and rebuilds the agent (the `_agent_cache` already keys
on an `mcp_fingerprint`).

### 8. No skill provenance / trust tracking
**What:** Nothing records whether a skill was shipped, written by the user,
written by the agent itself, or installed from elsewhere. Hermes has
`skill_provenance.py` (agent-authored vs. foreground) and `HubLockFile`
(install source). **Why it matters:** the project explicitly wants the agent
to author and improve its own skills (Deep Think, `propose_deep_think_task`,
reflection). Without a provenance marker, a future curator/cleanup step cannot
safely distinguish "a skill the agent autonomously created and may prune" from
"a skill the user hand-wrote and must never touch." It is also the
prerequisite for trust-based scanning (#2).
**Port sketch:** Add an `origin` field to `DiscoveredSkill` / `PlaybookSkill`
(`builtin` / `user` / `agent` / `marketplace`). Set it from `zone` + a
ContextVar (port `skill_provenance.py`) that `boot_for_tui` sets per agent
flavor — Deep Think / `propose_deep_think_task` runs mark writes as `agent`.
Persist it in the skill folder (a `.origin` file or a frontmatter field) so it
survives a restart.

### 9. No `scripts/` / linked-file affordance for playbook skills
**What:** Hermes's `skill_view(name, "scripts/foo.py")` lets the model pull a
specific script/reference/template/asset, and `skill_view` with no file lists
all linked files by category. JROS's `skill view` returns only SKILL.md text
(16 KB cap) and the bare `folder` path — the model must guess what files exist.
**Why it matters:** many skills are "instructions + a script to run." If the
script lives in `scripts/` and the model doesn't know its name, the skill is
effectively just the playbook text. Several shipped JROS skills already have a
`scripts/` dir (`red-teaming/godmode/scripts/parseltongue.py`).
**Port sketch:** Extend the `skill` tool in `core/tools/skills.py`: on `view`,
also `rglob` the skill folder and return a `files` dict bucketed into
`references/` `templates/` `assets/` `scripts/` `other` (hermes's exact
categories). Add a `file` argument so `skill(action="view", name=…, file="scripts/foo.py")`
returns that file's contents, sandbox-checked against the skill folder.

### 10. No central tool registry / per-tool metadata
**What:** Hermes's `ToolRegistry` is a single object with `ToolEntry` per tool
carrying toolset, emoji, `requires_env`, `check_fn` (availability probe with
30s TTL cache), `max_result_size_chars`, `dynamic_schema_overrides`. JROS has
no registry object — tools are closures in `_register_builtins`; `toolsets.py`
maintains a *separate* hand-edited `TOOLSETS` dict that has to be kept in sync
by hand. **Why it matters:** there is no single place to ask "is this tool
available right now" (`check_fn`) — `vision_analyze` is in the schema even
when the VLM can't load; no per-tool result-size cap; the `TOOLSETS` grouping
in `toolsets.py` will silently rot as tools are added (a tool in no toolset is
fail-open, which masks the drift).
**Port sketch:** This is the largest item and partly philosophical (pydantic-ai
owns dispatch). A pragmatic middle path: build a lightweight `ToolMeta`
registry that `_register_builtins` populates alongside the `@agent.tool_plain`
decoration — `{name: {toolset, tier, check_fn, max_result_chars}}`. Have
`toolsets.py` derive `TOOLSETS` *from* that registry instead of a hand-edited
dict, and have `llm_model._select_tool_schemas` consult `check_fn` to drop
unavailable tools from the schema.

### 11. No oversized-result persistence / turn budget
**What:** Hermes's `tool_result_storage.py` has a 3-layer budget: per-tool
threshold → persist oversized results to a sandbox file and hand the model a
preview + path → aggregate per-turn budget that persists the largest results
until under budget. JROS caps individual tools ad-hoc (`web_fetch` 8 KB,
`run_python` 200 KB, `skill` 16 KB) with no aggregate accounting. **Why it
matters:** a turn with several large tool results (read a big file, fetch a
page, run a verbose script) can blow the context window with no backstop;
`llm_model._select_tool_schemas` trims *schemas* on overflow but nothing trims
or offloads tool *results*.
**Port sketch:** Port `tool_result_storage.py` as `core/tool_result_storage.py`
— it is self-contained. Apply `maybe_persist_tool_result` in `_run_via_iter`
when a `ToolReturnPart` is observed (write the overflow to
`<instance>/skills/.tool_results/` and replace the content with a preview +
path the model can `read_file`). Add `enforce_turn_budget` across a turn's
tool returns.

### 12. No OSV / malware check on package installs
**What:** Hermes runs `osv_check.check_package_for_malware` against the OSV
database before an MCP-suggested package install. JROS's `install_package`
(tier-4, prompts the user) pip-installs whatever the model names with no
malware check. **Why it matters:** the lazy-deps comment in hermes notes a
real incident (`mistralai` quarantined for the Shai-Hulud worm). A tier-4
prompt asks the *human* to vet a package name they likely can't vet. An
automated OSV lookup catches known-malicious packages the human would wave
through.
**Port sketch:** Port `tools/osv_check.py` (155 lines, only needs an HTTP
client) as `core/osv_check.py`. Call `check_package_for_malware(package)` in
`core/venv.install_into_venv` before running pip; on a hit, refuse and return
the OSV advisory. Low effort, meaningful safety win, pairs with #3.

---

## Part D — What JROS does that hermes doesn't (or does better)

Keep these — they are real JROS strengths.

- **Per-skill scored benchmarking.** `skill_benchmark.py` + the
  `benchmark_skill` tool run a skill's `tests/benchmark.py`, record a JSONL
  history, and report the `delta` vs. the last run. Hermes has *no* per-skill
  benchmark. This turns "did my skill revision help?" into a measured number —
  exactly the self-improvement loop the project wants.
- **Smoke-test gate on code-skill load.** `skill_loader` runs each code
  skill's `tests/smoke_test.py` as a subprocess before registering it; a
  failure skips the skill and audits why. Hermes skills are playbooks so it
  has no equivalent — a JROS code skill cannot register broken.
- **6-tier permission model with one-way-door safe modes.** Even though
  coverage is thin (Part C #1), the *design* — `PermissionTier` enum,
  `PolicyMode` (NORMAL/READ_ONLY/PAUSED) where exiting a safer mode needs
  `human_override=True`, `contextvars`-scoped policy so subagents inherit it,
  per-skill `PermissionGrants` persisted to `permissions.json` — is cleaner
  and more robot-appropriate than hermes's approval-prompt engine.
- **Tamper-evident audit trail.** Every sandbox-relevant op, every `run_shell`,
  every permission denial is appended to `logs/audit.log`; `file_write` also
  git-auto-commits each agent-authored change as a real commit. Hermes logs to
  agent.log but has nothing as deliberate as the append-only audit log + git
  authorship history.
- **Run-and-fix loop for generated code.** `_run_with_fix_loop` detects a
  failed `execute_code` or a `syntax_ok:false` write and injects exactly one
  "read it, fix it, re-run it" pass, with the prior tool calls as history.
  Hermes leaves this to the model. For the code-writing path JROS's loop is a
  concrete reliability win.
- **Hard sandbox-by-default for file writes.** All writes resolve under
  `<instance>/skills/` with absolute-path / `..` / symlink-escape rejection,
  no environment-backend configuration required. Hermes's file safety depends
  on which environment backend is active.
- **Toolset auto-capture for skills.** `_ToolCapturingAgent` records exactly
  which tools a code skill registered, so a skill automatically *becomes* a
  named loadable toolset with zero hand-editing — a nice touch hermes's
  hand-maintained toolset config doesn't have.
- **Loop backstops.** `_MAX_TOOL_CALLS`, `_MAX_IDENTICAL_CALLS`,
  `_semantic_failure_signature` + `_MAX_SEMANTIC_FAILURES` guarantee a turn
  terminates and catch a model spinning the same failing call — a clean,
  small safety net.
