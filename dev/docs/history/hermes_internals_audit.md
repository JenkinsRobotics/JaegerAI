# Hermes vs. JROS — Internals Port Audit (non-tool / non-skill)

**Date:** 2026-05-21
**Scope:** Everything in the hermes-agent tree that is *not* a tool or a
skill — `agent/` internals (~22 k LOC, 70 files), `gateway/`, `plugins/`,
`providers/`, `cron/`, `acp_adapter/`, `environments/`, and the standalone
runners. Companion to `docs/hermes_tool_skill_audit.md`.
**Method:** Read module docstrings/headers across both trees; verified
each JROS "gap" claim against source. No assumptions.

## Framing — why most of this is a "skip"

Hermes-agent is a **broad** framework: a multi-provider inference layer
(Anthropic, Bedrock, Gemini, Codex, Kimi…), a 37-platform messaging
gateway, an RL-training integration (Atropos), an ACP server, full LSP
support. Jaeger-OS is a **focused** one: a Mac-native, local-first,
voice-first OS for *one* embodied agent at a time (Lilith on a desktop,
JP01 in hardware). Most of hermes's non-tool bulk exists to serve goals
JROS has deliberately *not* taken on — and `core/llm_client.py:19` even
documents the choice ("no context_compressor, no custom_providers…").

So this audit sorts hermes's internals three ways: a **focused set of
genuine ports** for now (Part A — 10 items), a set of **roadmap
capabilities** JROS *does* want but later and in their own folders
(Part B), and the genuine **skips** — breadth JROS isn't chasing
(Part C). The point is a clear, durable record so none of it is
re-litigated.

---

## Part A — Port candidates, ranked

### A1. Conversation context compression — **PORT, HIGH**
**Hermes:** `agent/context_compressor.py` (~800 LOC) + the pluggable
`agent/context_engine.py` ABC. When the transcript nears the token
limit, it summarizes the *middle* turns into a structured summary,
protects a head/tail window, prunes tool output before summarizing, and
iteratively merges summaries.
**JROS today:** Nothing. `core/llm_client.py:19` lists "no
context_compressor" as an explicit non-feature; `core/trajectory.py`
only *exports* the transcript; `llm_model._select_tool_schemas` trims
*schemas* on overflow but never the conversation. A long voice session —
exactly the JROS use case — will grow the transcript until the model
truncates or errors, with no graceful degradation.
**Why it fits:** A voice-first agent that runs for hours is the worst
case for an unmanaged context window. This is the single biggest missing
runtime safeguard.
**Port sketch:** Port `context_compressor.py` as `core/context_compressor.py`,
adapted to the pydantic-ai message list (`ModelRequest`/`ModelResponse`
parts) instead of hermes's OpenAI-dict transcript. Invoke it in
`_run_via_iter` (or its R4 successor) when `message_history` token
estimate crosses a threshold. **Fold into the main-loop R4–R8 rebuild
(`docs/main_loop_review.md`)** — it belongs there alongside tool-audit
**#5** and **#11**, not as a bolt-on. Skip the pluggable `ContextEngine`
ABC; JROS needs one compressor, not a plugin point.
**Effort:** Moderate (the message-format adaptation is the real work).

### A2. Skill Curator — ✅ DONE 2026-05-21
**Shipped:** `core/curator.py` — `assess` classifies every playbook skill
(protected / active / stale / unused); `run_curation(apply=False)` is a
dry run by default; `archive_skill` / `restore_skill` / `list_archived`
make archiving a **non-destructive, reversible move** (the archive
directory *is* the backup — no tar snapshot needed). Hard invariants,
all test-pinned: only `origin == "agent"` skills are ever touched, a
`.pinned` skill is protected, a never-used skill is reported but not
auto-archived, nothing is ever deleted. Wired a read-only `curate`
action into the `skill` tool. Consolidation (merging near-duplicates)
deliberately deferred — it needs LLM judgement. 19 tests.
**Hermes:** `agent/curator.py` (~600 LOC) + `agent/curator_backup.py`
(~300 LOC). A background pass that maintains *agent-authored* skills:
transitions lifecycle states (active → stale → archived), consolidates
near-duplicates, and **never auto-deletes** — only archives, and only
skills it is allowed to touch. `curator_backup.py` takes a tar.gz +
manifest snapshot before any mutation so every change is reversible.
**JROS today:** Nothing — and the groundwork is already laid *for* it.
`core/playbook_skills.py:30` literally comments the provenance `origin`
field is "for trust decisions and a future curator." Tool-audit **#8**
(provenance) was built as the Curator's prerequisite; **#4** (usage
telemetry) and `skill_benchmark.py` give it the signals; `reflection.py`
+ `deep_think.py` generate the skills it would curate. The Curator is
the missing capstone of the self-improvement loop.
**Why it fits:** The project's stated goal is an agent that authors and
improves its own skills. Without a curator, the skill library only ever
grows — Deep Think keeps adding, nothing prunes. Provenance (#8) makes
this *safe*: the Curator only ever touches `origin == agent` skills,
never a hand-written `user`/`builtin` one.
**Port sketch:** Port as `core/curator.py` + `core/curator_backup.py`.
Drive lifecycle from `usage_stats.json` (#4) + `benchmark_history.jsonl`.
Gate every action on `origin == "agent"` (#8). Run it from `cron_runner.py`
daily housekeeping, or as a Deep Think task type. Hard invariant, copied
from hermes: archive-only, snapshot-first, never delete.
**Effort:** Moderate–large. Do it *after* the tool/skill audit's #5/#7/
#10/#11 — it depends on #8/#4 which are already done, so it is unblocked,
but it is a feature, not a gap-fix.

### A3. Log/output secret redaction — ✅ DONE 2026-05-21
**Shipped:** `core/redact.py` — `redact_text` / `redact_obj` / `mask_secret`,
wired into `_common._audit` (the audit log) and `trajectory.add_tool_result`
(the JSONL export). 17 tests.
**Hermes:** `agent/redact.py` (~300 LOC) — regex secret-scrubbing that
masks API keys/tokens while keeping first/last chars for debuggability;
applied before anything hits a log or the screen.
**JROS today:** Nothing. `core/trajectory.py:186` admits the gap in a
comment — the *caller* "is responsible for redacting," and no caller
does. `run_shell` writes `command[:500]` straight into `logs/audit.log`
(see the tool/skill audit, Part A); tool args land in trajectories and
usage logs verbatim. A command or skill that handles a credential leaks
it into the tamper-evident audit log permanently.
**Why it fits:** It is a small, self-contained safety win that pairs
directly with the MEMORY item "Three Laws + safeguard hardening must
land before the Jaeger port." A tamper-evident audit log that contains
plaintext secrets is a liability, not a safeguard.
**Port sketch:** Port as `core/redact.py`; call `redact()` in
`safety._audit` / the audit-log writer, in `trajectory.py` on export,
and in `usage_stats.record_tool` arg capture. Pure regex, no deps.
**Effort:** Small.

### A4. `@`-reference expansion in user input — ✅ DONE 2026-05-21
**Shipped:** `core/context_refs.py` — `expand_references` inlines `@file`
and `@url` content; wired into the TUI text turn (`_run_text_turn`).
Email addresses are not mis-detected; file reads go through the A5 guard.
8 tests.
**Hermes:** `agent/context_references.py` — parses `@file`, `@folder`,
`@url`, `@git`, `@diff`, `@staged` in a user message and expands them
inline before the turn runs.
**JROS today:** The rebuilt TUI has slash commands but no `@`-refs (grep:
none). To get a file's contents into a turn the user must ask the agent
to call `read_file` — an extra round-trip for something the user already
knows the path of.
**Why it fits:** Pure UX, self-contained, and a natural fit for the TUI
that was just rebuilt to hermes parity. `@file`/`@url` are the high-value
subset; `@git`/`@diff`/`@staged` are coding-agent features JROS can drop.
**Port sketch:** A small `interfaces/tui` (or `core/`) preprocessor that
rewrites `@path` → file contents and `@url` → `web_fetch` result before
the text reaches `_run_via_iter`. Reuse `_resolve_read` for sandboxing.
**Effort:** Small.

### A5. Sensitive-path read guard — ✅ DONE 2026-05-21
**Shipped:** `core/file_safety.py` — `is_sensitive_path` refuses a read
that resolves into `~/.ssh`, `.aws`, `.kube`, `.gnupg`, `.docker`, a
`.env`, the macOS keychain, or a known secret file; wired into
`_resolve_read` (reads are unconfined since #1, so this is the gap).
`.env.example`-style templates stay readable. 37 tests.
**Scope note:** `run_shell` was *not* wired — parsing an arbitrary shell
command for sensitive paths is false-positive-prone, and `run_shell` is
already tier-4 (human-approved) + A9-floored. The real gap was the
tier-0 unconfined `read_file`, which is now closed.
**Hermes:** `agent/file_safety.py` — a blocklist that refuses reads/writes
to `~/.ssh`, `.env`, `~/.kube`, etc.
**JROS today:** File *writes* are already hard-confined under
`<instance>/skills/` (strong — Part D of the tool/skill audit). The gap
is `run_shell`: it is explicitly *not* filesystem-confined, so a
tier-4-approved command can still `cat ~/.ssh/id_rsa`. Tier-4 asks a
human to vet the command, but a human waves through commands they can't
fully parse.
**Why it fits:** Defense-in-depth behind the tier prompt, same spirit as
the OSV check (#12) — catch what the human approver would miss.
**Port sketch:** Port the blocklist as `core/file_safety.py`; consult it
in `run_shell` (reject a command whose argv touches a blocked path) and
as a second check in `_resolve_read`.
**Effort:** Small. Lower priority than A3 because the write surface is
already sandboxed; this only hardens `run_shell`.

### A6. SKILL.md preprocessing — ✅ DONE 2026-05-21
**Shipped:** `core/skill_preprocessing.py` — `preprocess_skill` expands
`{{date}}` / `{{instance_name}}` / `{{skill_folder}}` / `{{os}}` … in a
SKILL.md body; wired into the `skill` tool's `view` action. Unknown
placeholders are left untouched. 7 tests.
**Scope note:** template variables only. Hermes's inline-shell execution
was deliberately **not** ported — running shell while merely *viewing* a
skill would be an un-gated `run_shell` bypassing the tier system.
**Hermes:** `agent/skill_preprocessing.py` — expands template variables
and runs inline shell snippets in a SKILL.md before the model sees it.
**JROS today:** `playbook_skills.py` returns SKILL.md body raw (16 KB
cap). A playbook can't parameterize itself or inject a computed value.
**Why it fits:** Extends the tool/skill audit's **#9** (`scripts/`
affordance) — together they make playbook skills meaningfully more
capable. Lower priority because raw playbooks already work.
**Port sketch:** Add a preprocessing step in `playbook_skills` / the
`skill` tool's `view` action. **Security note:** inline-shell execution
in a skill body must run *through* the tier system and the
`skills_guard` scan (#2) — do not let preprocessing become an
un-gated `run_shell`.
**Effort:** Small–moderate.

### A7. Jittered retry backoff — ✅ DONE 2026-05-21 (folded into A8)
**Hermes:** `agent/retry_utils.py` — jittered exponential backoff.
**JROS today:** The `core/external_model.py` cloud path has no shared
backoff helper.
**Why it fits:** `retry_utils.py` is one of the three files in the
cloud-error-handling cluster — port it **together with A8**, not alone.
**Effort:** Trivial (folded into A8).

### A8. Cloud error handling — ✅ DONE 2026-05-21
**Shipped:** `core/cloud_errors.py` — `classify_exception` (auth /
not_found / rate_limit / transient / unknown, SDK-agnostic),
`friendly_message`, and `retry_call` (jittered backoff — A7). Wired into
`ExternalModelClient.chat` (retries 429 / transient) and
`connectivity_check` (classified `detail` instead of a raw repr).
16 tests.
**Hermes:** a three-file cluster — `agent/error_classifier.py` (an
API-error taxonomy that maps a failure to a recovery action: retry /
rotate key / fall back / compress / abort), `agent/rate_limit_tracker.py`
(parses rate-limit headers, formats the wait), and `agent/retry_utils.py`
(A7 — jittered backoff).
**JROS today:** Nothing. With six providers wired — four of them cloud
(`ollama-cloud`, `openai`, `anthropic`, `gemini`) — JROS still has no
classification of a provider failure. pydantic-ai surfaces a raw error;
the agent can't tell "bad API key" from "rate-limited, retry in 30s"
from "model not found" from a transient 500.
**Why it fits:** External models stopped being a marginal path the day
Gemini + the cloud `/model use` work shipped (B2). A classified error
plus a sane retry is now load-bearing UX: a 429 should back off and
retry, a 401 should say "your <provider> key is bad" and stop, not spin.
**Port sketch:** Port the three files as `core/cloud_errors.py` (or a
small `core/net/` package). Classify in the `external_model.py` call
path and `ExternalModelClient.connectivity_check`; on a classified 429,
retry with `retry_utils` backoff; on 401/404, surface a plain one-line
message. Pairs with audit **#7** (MCP OAuth) — both touch the network.
**Effort:** Small–moderate. Three small, self-contained files.

### A9. Hardline command blocklist — ✅ DONE (2026-05-21)
**Hermes:** `tools/approval.py` carries a **hardline blocklist** — ~12
patterns refused **unconditionally**, below every bypass mode and below
the approval prompt itself.
**JROS gap:** `run_shell` was gated at tier-4 (PRIVILEGED) — a human
approves the command — but its *content* was never inspected. Nothing
stopped an approved `rm -rf /`, and a human approver can't always parse
what a command really does. The tier prompt was the only gate.

**Shipped:** `core/command_guard.py` — `check_hardline(command) -> str | None`
plus a `hardline_guard` decorator. Applied to `run_shell` **outside**
`@requires_tier`, so a catastrophic command is refused *before* the tier
prompt ever fires and the tool body is never reached. Covers: recursive
`rm` on root / home / a top-level system dir, `mkfs`, `dd` to a raw disk
device, redirect into a raw device, the fork bomb, and
shutdown/reboot/halt/poweroff — each **command-position-anchored** (so
`echo shutdown` is not flagged) and **quote-normalised** (so
`rm -rf "/"` is caught). Deliberately conservative: `/tmp`, deep
subpaths, and local recursive deletes pass through to the tier prompt —
a false positive is worse than a miss. 43 tests; 423 pass.

**Scope note:** `run_shell` only. `run_python` / `run_in_venv` execute
Python, not shell — a shell-pattern blocklist does not apply to them.
Hermes's 47-pattern "dangerous" set and the tirith binary stay skipped;
JROS's 6-tier model is the foundation, this is just the floor under it.

### A10. Memory manager + provider pipeline — **PORT, HIGH**
**What JROS wanted:** keep the instance-scoped store (it is good), but
give the framework hermes's memory *pipeline and manager* layer.

**Hermes:** `agent/memory_manager.py` (orchestrator) + `agent/memory_provider.py`
(a `MemoryProvider` ABC). The manager owns the **lifecycle**: `prefetch()`
before a turn (recall injected as a `<memory-context>` block),
`sync_turn()` after (persist the exchange), `system_prompt_block()` (a
static block), plus hooks — `on_session_switch()`, `on_delegation()` (a
parent observing a sub-agent), `on_pre_compress()` (extract insight
before the transcript is compressed). Providers are pluggable; the
*built-in* one is a plain on-disk store.
**JROS today:** `core/memory.py` is a flat module of functions —
`remember` / `recall` / `forget` / `search_memory` over instance-scoped
`facts.json` + `episodic.jsonl` (atomic writes, fcntl locks, a lazy
sentence-transformers semantic index). It is **good storage**, but there
is no *pipeline*: nothing prefetches memory before a turn or syncs it
after — memory only moves when the model explicitly calls the `memory`
tool. Recall is entirely the model's responsibility.
**Why it fits:** A `MemoryManager` turns memory from a tool the model
*might* call into a *pipeline* that always runs — relevant facts
prefetched into every turn, the exchange synced after. `on_pre_compress`
is the clean hook for **A1** (context compression); `on_delegation` is
exactly the seam the locked V4 **unified-subagent-memory** decision
needs. This is an architecture upgrade, not a storage change.
**Port sketch:** Add `core/memory_manager.py` + a `MemoryProvider` ABC.
**Keep `core/memory.py` exactly as is** — wrap it as the built-in
`InstanceMemoryProvider`, the default and (for now) only provider. The
manager runs `prefetch` / `sync_turn` around `_run_via_iter`. Skip the
external SaaS providers (Honcho, Mem0) — the ABC means they *could* be
added, but cloud memory is not a JROS goal. Align the hooks with the V4
unified-subagent-memory decision rather than re-opening it.
**Effort:** Moderate–large — it rewires how memory meets the loop, but
the storage layer is reused untouched. Pairs with A1 in the loop rebuild.

---

## Part B — Roadmap (wanted, but later — in their own folders)

These are **not** skips. They are capabilities JROS genuinely wants;
they are deferred, and — important — each gets its **own dedicated
folder** rather than being wedged into `skills/`, `tools/`, or the agent
loop. Hermes is the reference implementation for when the time comes.

### B1. Reinforcement-learning training — new `rl/` package
**Hermes:** `environments/` (~170 KB) is hermes's RL layer — the Atropos
integration. `hermes_base_env.py` (abstract Atropos environment),
`agent_loop.py` (a reusable multi-turn rollout engine), `tool_context.py`
(a per-rollout tool handle that reward functions call), concrete envs
(`web_research_env.py`, `agentic_opd_env.py`, `hermes_swe_env.py`), and
`tool_call_parsers/` (12 model-specific parsers). Plus `rl_cli.py`,
`mini_swe_runner.py`, `batch_runner.py`, `toolset_distributions.py`, and
`tinker-atropos/`.
**JROS direction:** RL training *is* a key future capability — the robot
will train. It must **not** live under `skills/` (a trained policy is
not a playbook) and must not be bolted onto the agent loop. Give it a
dedicated top-level package: **`src/jaeger_os/rl/`**.
**Port sketch (when scheduled):** Seed `rl/` from hermes `environments/`
— `agent_loop.py` + `tool_context.py` are the reusable rollout core; the
concrete envs are examples to adapt. Keep the Atropos dependency
lazy/optional (`core/lazy_deps.py`). **Open design question to settle
first:** does JROS RL target the LLM tool-use policy (hermes's scope),
the `embodiment/` motor-control layer, or both? Those are different
reward surfaces and may want sub-packages (`rl/policy/`, `rl/motor/`).
**Effort:** Large — a milestone of its own.

### B2. External-model providers — ✅ coverage done (2026-05-21), abstraction deferred
**What JROS wanted:** external models hooked up "just like Ollama" —
Claude, OpenAI and Gemini all selectable as options.

**Shipped (2026-05-21):**
- **Gemini** added to `core/external_model.py` + `ExternalModelConfig` —
  via Google's **OpenAI-compatible endpoint**
  (`generativelanguage.googleapis.com/v1beta/openai/`), so it rides the
  existing `openai` path with **no native adapter** (hermes's heavy
  `gemini_native_adapter.py` / `gemini_schema.py` correctly stay
  skipped). `GEMINI_API_KEY` is the conventional env var.
- `openai` and `anthropic` already worked at the config level but were
  not TUI-selectable; the `/model use …` command now exposes
  `openai` / `anthropic` / `gemini` (plus `claude` / `google` aliases),
  the interactive `/model` picker has a "type a model" entry for each,
  and `/model list` documents them.
- Each cloud provider now stores its key under its **own** credential
  name (`openai_api_key`, `anthropic_api_key`, `gemini_api_key`,
  `ollama_cloud_api_key`) — switching providers no longer clobbers
  another's key. The key prompt is provider-aware.
- 10 tests added; 377 pass.

**Still deferred — the `ProviderProfile` abstraction itself.** Hermes's
`providers/` makes each provider one declarative profile (auth,
transport, model catalog, hooks). JROS now has 6 providers wired with
modest branching in `external_model.py`; that is fine *today*. Port the
single-source-of-truth pattern only when the branching genuinely hurts
(≈next 2–3 providers). Not a new folder yet — keep it in `core/` until
then.

### B3. Image & video generation — new `media/` package
**Hermes:** `agent/image_gen_provider.py` + `image_gen_registry.py` +
`video_gen_provider.py` + `video_gen_registry.py` + `image_routing.py` —
pluggable backend ABCs + registries; backends ship as plugins
(`plugins/image_gen`, `plugins/video_gen`).
**JROS today:** `core/tools/vision.py` has a single inline `generate_image`
(SDXL). Functional, but image *and* video generation as a real feature
area shouldn't live inside the vision tool.
**JROS direction:** Image and video generation are wanted down the line,
in their **own folder** — e.g. `src/jaeger_os/media/` (or `generation/`)
— not inside `tools/vision.py`.
**Port sketch:** A `media/` package with a provider ABC + registry;
migrate the current SDXL path in as the first image backend, add video
later. Surface through a thin tool wrapper so the model still sees one
`generate_image` / `generate_video` tool.
**Effort:** Moderate; deferred until a second backend (or video) lands.

---

## Part C — Considered and skipped

| Hermes area | ~Size | Why skip |
|---|---|---|
| `gateway/` — 37-platform messaging | ~25 k LOC | JROS's `plugins/messaging_gateway.py` + Discord/Telegram/iMessage bridges + bridge registry are deliberately the right *scale* for one personal agent. 37 platform adapters is scope JROS does not want. |
| Docker/Modal/SSH/Daytona terminal backends | (part of `environments/`) | The tool/skill audit already concluded JROS doesn't need the multi-backend environment abstraction — local execution + the venv sandbox is the design. (Note: the *RL* half of `environments/` is **not** skipped — see Part B1.) |
| `acp_adapter/` + `acp_registry/` + `mcp_serve.py` — expose the agent *as* a server to Claude Code / Cursor / MCP clients | ~150 KB+ | JROS's direction is *consuming* MCP (tool/skill audit **#7**), not being driven by an IDE. A robot OS is not an IDE backend. Revisit only if "drive Lilith from an editor" becomes a real goal. |
| `agent/lsp/` — language-server diagnostics | ~3 k LOC | JROS is a voice-first robot OS, not a coding agent in arbitrary repos. Could lift agent-authored *skill* code quality, but 3 k LOC is too heavy for that payoff today. Reconsider only if skill-authoring quality becomes a measured bottleneck. |
| Heavy vendor adapters — Bedrock, Gemini native, Codex app-server, Kimi, Cloud Code | ~4.5 k LOC | External models *are* wanted (Part B2), but via the lean `ProviderProfile` pattern — not by porting 4.5 k LOC of vendor-specific adapters. Port a transport only when a provider JROS adopts needs it. |
| External memory SaaS providers — Honcho, Mem0, Holographic, … | varied | The manager + provider *pipeline* is now a port — see **A10**. The external SaaS *providers* stay skipped: JROS's instance-scoped store is the built-in provider, and cloud memory SaaS is not a JROS goal. |
| Hermes's command-pattern approval engine — `approval.py` (47 dangerous-pattern set), `tirith_security.py`, smart-approval LLM | ~60 KB+ | JROS's 6-tier model is the better foundation (tool/skill audit, Part D). Only the unconditional **hardline blocklist** is worth taking — see **A9**. |
| `agent/prompt_caching.py`, `models_dev.py`, `subdirectory_hints.py` | ~900 LOC | Prompt caching is an Anthropic-API feature (llama.cpp has its own KV cache); `models_dev` duplicates `core/model_discovery.py`; subdirectory hints is a coding-agent feature. |
| Web-search provider registry | ~500 LOC | `core/tools/web.py` already has a multi-backend fallback chain — the capability exists; the registry pattern is nicer but not worth a rewrite. |
| `agent/insights.py`, `account_usage.py`, `usage_pricing.py` | ~800 LOC | Cloud cost/usage analytics; JROS is local-first. `core/usage_stats.py` (#4) already covers tool/skill telemetry. |
| `agent/i18n.py`, `markdown_tables.py`, `display.py` | ~600 LOC | JROS is single-language; the TUI was just rebuilt to hermes parity in its own idiom. |
| `agent/shell_hooks.py` | ~400 LOC | A user-config'd shell-hook system — a feature JROS hasn't asked for. The harness-level hooks belong to the *runtime*, not the agent. |
| `trajectory_compressor.py` | ~moderate | Post-hoc compression of *saved* trajectories for training data — distinct from live context compression (A1). Revisit alongside the RL work (B1) if training-data prep needs it. |
| `hermes_state.py` — SQLite + FTS5 session store | ~moderate | A genuine nicety (searchable session history) but JROS's single-user scale doesn't demand FTS. Note as a *possible* future upgrade if `/history` search is wanted; not a port. |
| `hermes_bootstrap.py` | tiny | Windows UTF-8 fix; JROS is Mac-native. |

---

## Part D — Already covered (no port needed)

- **Cron / scheduling** — `core/cron_runner.py` + `CronRunner` + the
  scheduling tools already match hermes `cron/`. Hermes's version is
  gateway-coupled (delivery routing to channels); JROS's is instance-scoped.
- **Plugin architecture** — JROS has its own `plugins/<name>/` convention
  (`__init__.py` + smoke test + `plugin.yaml`). No need for hermes's.
- **Tool-loop guardrails** — hermes `agent/tool_guardrails.py` ≈ JROS's
  `_MAX_TOOL_CALLS` / `_MAX_IDENTICAL_CALLS` / `_semantic_failure_signature`
  loop backstops (tool/skill audit Part D).
- **Thinking-block scrubbing** — hermes `agent/think_scrubber.py` ≈ JROS
  `llm_model._DRIFT_PATTERNS` + `test_drift_parser.py`.
- **Kanban** — hermes's `plugins/kanban` ≈ JROS `core/board.py`.
- **Curator backup/snapshot of skills** — partially overlaps JROS
  `skill_package.py` packaging, but the *snapshot-before-mutation* part is
  genuinely missing → covered under A2.

---

## Scorecard & recommended sequencing

**Port now (10) — 8 done, 2 remaining.** ✅ done 2026-05-21:
A2 Curator · A3 redaction · A4 `@`-refs · A5 file-safety guard ·
A6 SKILL.md preprocessing · A7 retry backoff · A8 cloud error handling ·
A9 hardline blocklist. **Remaining:** A1 context compression ·
A10 memory manager + provider pipeline — both inside the loop rebuild.

**Roadmap (3):** B1 RL training → `rl/` (deferred) · B2 external-model
providers — **coverage done** (Gemini added, all cloud providers
TUI-selectable); the `ProviderProfile` abstraction still deferred ·
B3 image/video generation → `media/` (deferred).

**Skip:** gateway, Docker/Modal/SSH backends, ACP/MCP-serve, LSP, heavy
vendor adapters, external memory SaaS, hermes's command-pattern approval
engine, prompt-caching et al., web-search registry, cloud analytics,
i18n/display, shell-hooks, `trajectory_compressor`, `hermes_state`/bootstrap.

**The 2 remaining ports are milestone-scale — not "small ports":**
1. Finish the tool/skill audit first (#5, #7, #10, #11).
2. **A1 (context compression) + A10 (memory pipeline)** — do both
   *inside* the main-loop R4–R8 rebuild (`docs/main_loop_review.md`),
   with #5 and #11. They touch the same load-bearing loop code, and
   A10's `on_pre_compress` hook is how A1 plugs in. This is the rebuild
   milestone — not an autonomous one-file port.
3. **B2 (provider abstraction)** — incremental; trigger is the ≈4th–5th
   external provider, not a calendar date.
4. **B1 (RL → `rl/`)** and **B3 (image/video → `media/`)** — each its own
   scheduled milestone with its own folder; not blocked by anything above,
   but large enough to plan separately. B1 needs its policy-vs-motor
   design question settled first.
