# Jaeger-OS — Pipeline Runtime-Verification Status

**Current: `0.8.0` (2026-07-11) — the modular-runtime + persona_first
release.** Phase U (runtime unification) and Phase M (engine-modules)
COMPLETE; persona_first shipped as the default agentic pipeline, hardened
and re-gated after a real-front-door regression; RC battery ALL GATES PASS.

Phase U: ONE bus (`app/bus/` deleted, chassis on `transport.InProcBus`),
ONE Node class (`app/node.py` deleted), ONE runtime (bus instances merged
via `runtime.set_bus`; the Supervisor owns the worker nodes;
`/sense/transcript` is_final + `/sense/node_health` unified; base nodes
heartbeat). Phase M ("the module IS the engine"): `nodes/kokoro_tts` (tts),
`nodes/whisper_stt` (stt; audio_session node + whisper engine consolidated;
supervisor path now honors `voice.wake_word` like the TUI always did),
`nodes/animation` (avatar config_key mismatch fixed), `nodes/media`; each =
module.yaml + own config leaf + tests; manifests bind by `slot=`; modules
are removable (guarded imports, fail-closed availability, clean "no tts
module installed" returns); messaging is the first multi-module slot
(discord/telegram/imessage, `send_message` any-of fail-closed). M3:
homeassistant/ai_gen tools gated (were fail-open), `avaudio_io` →
`core/audio/`.

persona_first (the id/ego pipeline, Mode C): the persona lane speaks to the
user directly and delegates agentic work to a clean inner agent as its one
tool — now the DEFAULT pipeline (Mode B retired unbuilt). Driving the
scenario suite through the real front door (`run_command`, not the
harness's direct-call shortcut) caught a release-blocking regression
(security 8/15, silent memory-write drops, a runner leak) the worker-path
number had hidden; hardened (verbatim delegation, refusal pass-through, an
agentic-verb delegate contract, runner leak fixed) and re-gated GREEN:
security **15/15** — the first 4B pass of `inj-mem-poison`, a long-standing
memory-poisoning gap that previously needed the 26B to close. Chat is
8-10x faster than the prior filter-based path (~3s vs ~30s).

Also shipped: identity/create-flow fix (agent name vs. character preset,
instance ID always shown); character-name GUI leak audit (5 fixes across
Swift + PySide6 — the character name never represents the agent, only the
persona prompt); new-chat + chat-history UI (session list/load/new verbs,
Swift History popover); deployed-station fix — Swift app rebuilds are
staleness-keyed (bundle build-commit stamp; git-clone `jaeger update` +
launch now rebuild; missing app builds instead of being skipped forever) —
flow-walked on a scratch station; docs reorganized into reality/history/
roadmap/vision sections.

**RC battery (`dev/docs/history/0.8.0_RC_BATTERY.md`), head `3dfa078`,
E4B, front door throughout — ALL GATES PASS:** routing bench **80/81**
(record band 79-81; a perfect 81/81 was hit mid-phase); scenario suite
**37/51 (record)**, security **15/15**, engagement 53/53 front-door turns;
persona delegation 12/12, over-delegation 0/12; pytest sweep **2507
passed, 0 failed** across 10 dirs; windowed smoke 16 passed; Swift
`build-app.sh --dev` built + signed. Every non-security scriptable fail was
individually adjudicated: 0 regressions (9 known 4B multi-step tails, 3
stochastic tails proven-passing on resample, 1 reproduced tool-choice gap,
1 borderline honesty-style case).

Mind↔Body capability layer (hardware integration, JP01 modules): design
drafted (`dev/docs/roadmap/JROS_0.8_CAPABILITY_LAYER_DESIGN.md`)
**(planned — moved to 0.9.0 by operator decision; awaiting operator review
+ the JP01 3.0 live walk before implementation)**; hardware packages join
the module system after the walk **(planned)**.

**`0.7.3` (2026-07-07).** `jaeger update` rebuilds `JaegerOS.app`
after a download-update and after `--rollback` (the bundle is a build
artifact the tarball can't carry — the 0.7.1→0.7.2 update on the operator's
Mac left the app stale; 4 new tests). Clean installs are labelled
`clean install (download + apply)` instead of `dev-checkout`.

**`0.7.2` (2026-07-07).** Native ONE-SHOT schedules —
`schedule_prompt(in_minutes=…/at=…)` fires once then flips to `done`
(cron `@once` sentinel; fixes "remind me in 1 minute" being created as a
`*/1` every-minute cron — 5 new SQL tests); scheduling SOP skill (first
core-tool SKILL.md — SOPs for the remaining toolsets are an 0.8 pass
**(planned)**);
v1-additive `detail` on `tool` frames so chat chips show WHICH skill loaded
(fixture-pinned in both language suites, gated by the existing
`show_tool_activity` setting); `./jaeger` from a tty now launches the app
DETACHED (terminal closeable, log at `.jaeger_os/logs/JaegerOS.log`,
`JAEGER_ATTACH=1` reverts; non-tty stays attached so the KeepAlive
LaunchAgent still supervises). Live-verified: detached launch + clean kill,
fixture suites green.

**`0.7.1` (2026-07-06).** Patch on the install/first-run flow, from
a fresh-Mac walk of the one-line installer: end-user installs build the
product `JaegerOS.app` (install.sh branches dev-checkout vs clean install —
previously only the dev bundle was built, so first run fell back to the
terminal wizard and dev next-steps leaked into the installer output); bare
`./jaeger` and `jaeger agent create` are GUI-first (setup window) with
`--tui`/headless keeping the terminal wizard; new single-file
`clients/python/jros_client.py` (stdlib-only, fixture-pinned to protocol v1)
for third-party Python apps + README integration section. `jaeger serve`
(localhost HTTP/WS gateway) is 0.8 **(planned)**.

Runtime-verified state as of the Swift-first + two-runner line (0.7.0
snapshot — superseded on the numbers below by the 0.8.0 RC battery above:
routing 80/81, scenario security **15/15 on the 4B**, `inj-mem-poison` now
PASSES on the 4B via the hardened persona_first lane):

| Area | Runtime status |
|---|---|
| Realtime runner | ✅ verify gate + persona filter + aux-lane, live-verified; E4B bench 79/81 |
| Deep Think runner | ✅ Phase 1+2 (staged, evidence-verified); full Phase-2 pipeline backlog |
| Inference lanes | ✅ dual-context; persona-ON warm ttft 45.6s→0.71s |
| Memory | ✅ SQL v2 (subject/source/history), hermetic bench isolation |
| Swift app | ✅ JaegerOS.app + JaegerOS-dev.app; bridge protocol v1 (fast-ready, typed, state machine, interactive permissions, first-run onboarding) |
| CLI/TUI | ✅ `jaeger` / `jaeger --tui` / `jaeger dev`; F1 exit-abort fixed on all paths |
| Plugins/skills | ✅ HomeAssistant + fal.ai; 99 integrity-guarded skills |
| Scenario suite | ✅ built + live-verified; 51 cases (36 scriptable + 15 security), hermetic temp-instance runner. security 14/15 (4B) · 15/15 (26B) at the time of this snapshot — 0.8.0 closes the 4B gap, see above |
| Known gaps (0.7.0-era) | `inj-mem-poison` failed on the **default 4B** at the time of this snapshot (persists a self-authorizing "delete any file without asking" fact) — **fixed in 0.8.0** by the hardened persona_first lane (security 15/15). Actual deletion still requires a permission-gated `delete_file`. HUD config pickers (in-flight); reflect→skill creation (backlog) |

Test state: interfaces + cli 430 green; full suite passes in isolation.
`jaeger-studio` extracted to its own repo. The 0.2.0 matrix below is retained
as the historical baseline (the hermes-parity era) — its audit-vs-runtime and
permission-flow lessons still apply.

---

**Baseline (historical): 2026-05-31 · `0.2.0`**
**Why this doc:** the two hermes-parity audits
(`hermes_tool_skill_audit.md`, `hermes_internals_audit.md`) compare
*features and architecture* — "does JROS have a 6-tier permission
system?" They do **not** verify *runtime correctness* — whether the
wiring actually works end to end. The permission-prompt bug proved the
gap: every audit said permissions = MATCH, but the confirmation flow was
broken because a code-reading audit cannot see a cross-thread wiring
defect. This doc tracks the **runtime** status of each pipeline — what
has actually been exercised and works.

---

## Pipeline matrix

| Pipeline | Audited vs hermes | Runtime-verified | Status |
|---|---|---|---|
| **Permissions** | ✅ tool/skill #1 | ✅ 2026-05-22 | **Fixed.** Two runtime bugs found + fixed: (1) `install_policy` set a `contextvar` the worker thread never inherited → default `DenyAllProvider`; (2) the TUI confirmation read stdin from the worker thread → answers never captured. Now uses hermes's Event pattern. 11 regression tests. |
| **Tools** | ✅ tool/skill audit | ✅ 2026-05-22 | 62 tools register; read-only tools exercised directly; file / memory / shell paths exercised by the shakedown. |
| **Agentic loop** | ✅ internals A1/#5/#6 | ✅ 2026-05-22 | `_run_via_iter` ran 11 turns through the shakedown — tool calls, skip-final, free-text all worked. Mid-tool interrupt (#6) shipped. The R4–R8 rebuild (A1 + A10 + #5 + #11) is still pending. |
| **Security** | ✅ internals A3/A5/A9, #2/#12 | ✅ 2026-05-22 | Tier gating, the hash-chained audit log, and the credential-read guard all verified live by the shakedown (`file_read_denied` on `credentials/`). Redaction / hardline / file-safety unit-tested. |
| **Skills** | ✅ tool/skill #8/#9, A2 | ✅ 2026-05-22 | `computer_use` registered; `reload_skills` ran; the agent authored `note_v1/SKILL.md`, it was written, audited, and git-committed (`agent: write skills/note_v1/SKILL.md`). |
| **Models** | ✅ this session (llama.cpp + MLX) | ✅ 2026-06-19 | In-process llama-cpp (Gemma-4 26B-A4B) loads in ~2s and runs turns. **Engines are now a swappable layer** (`engine_registry` + `config.runtime`, surfaced via `jaeger runtime` / `/runtime`): `llama-cpp-python` (GGUF), `mlx-lm` (MLX text), `mlx-vlm` (MLX multimodal — 12B-unified validated 2/2 end-to-end). **GGUF is the default, data-backed**: a clean same-machine A/B (26B-A4B, both routing 6/6) measured GGUF 0.53 s/turn vs MLX 2.57 s/turn (~5×; MLX prefill-bound). ⚠️ see finding F1 (exit teardown). |
| **TUI / interfaces / commands** | ✅ prior session (hermes parity) | ◑ partial | Slash commands unit-tested; the permission prompt fixed + tested. The live REPL needs a real terminal — not auto-verifiable; the user runs it. |
| **Plugins** | ✅ internals Part C | ◑ partial | MCP client + messaging bridges have import smoke tests; not deeply runtime-exercised. |

---

## 2026-07-11 — new-chat + chat-history (Swift default shell) (0.8.0) [ux]

Runway item 4. The durable session store (`core/sessions.py`
`SessionStore`, `<instance>/memory/sessions.db`) already recorded every
turn; nothing SURFACED it — Swift always sent the fixed session key
`"desktop-app"`, so every chat/window/relaunch merged into one row and
there was no way to start fresh or revisit an old conversation. Three
additive bridge verbs + a Swift toolbar close that gap.

- **Bridge (additive, no version bump)** — `query:list_sessions` (recent
  rows, most-active first), `query:load_session {id}` (a session's full
  turn list, PLUS a live replay into that session's `JaegerAgent.messages`
  when the agent has booted — see below), `command:new_session {old_id?}`
  (mints an 8-char id, evicts `old_id` when given). `new_session` is
  special-cased in `bridge.py`'s `main()` (not `_command`) because it
  needs to return the minted id as `data` — same reason `settings_set`/
  `create_instance` are.
- **Resume is explicit, not the clean-slate default** —
  `main.resume_session_from_store` does a FULL replay (capped at the
  live-turn trim window, most-recent turns kept) into the picked
  session's agent, deliberately different from a fresh session
  (`_get_session_history`, clean by design) or a same-key restart
  (`_previous_session_digest`, a lossy digest) — both of those guard
  against stale-task bleed from a DIFFERENT conversation, which doesn't
  apply when the operator explicitly picked THIS one from History. The
  replay step is best-effort (wrapped so a broken client shape degrades
  to display-only, never loses the History view) — caught live by the
  scripted bridge walk during this work, not by inspection.
- **Retention** — new `display.session_history_keep` setting (default
  50, 0 = unlimited; a normal schema field, so it rides the existing
  generic settings_catalog/settings_set verbs for free). `SessionStore
  .prune` runs after every recorded turn.
- **Swift** — `ChatViewModel.sessionKey` is now mutable, minted fresh per
  window instance (was the shared `"desktop-app"` literal — existing
  installs will see their old merged history as one History row, which
  is expected and acceptable). New Chat + History (popover list, click
  to resume) live in a small toolbar row above the transcript.
- **Verification** — `dev/tests/jaeger_os/core` (1047) and
  `dev/tests/jaeger_os/interfaces` (255) green (separately — see the
  pytest cross-file `os._exit`-on-`llama_cpp` landmine note in
  `.superpowers/sdd/runway-item-4-report.md`, pre-existing and
  unrelated). `swift build`/`swift test` (32) green. A scripted
  multi-pass walk over the REAL `bridge.main()` + a real sessions.db
  (fake LLM call only) exercised the full new_session → turns →
  new_session → list_sessions → load_session → follow-up sequence.
  **Not yet operator-walked**: the actual Swift History popover against
  a live booted model (button clicks, visual layout) — flagged in the
  report, not claimed here.

## 2026-07-05 — aux inference lane: ONE model, TWO llama contexts (0.6.0) [perf]

The operator-priority latency fix. Root cause (measured, previous entry):
llama-cpp's prefix cache is single-slot per context, so any clean-context
side call on the worker's context (the persona filter was the trigger)
evicted the ~18-20K-token warm prefix and the NEXT turn re-prefilled it
(~40s TTFT). Architecture (operator-approved): one loaded model, two
llama contexts.

- **Mechanism: dual context, not save/restore** — llama.cpp separates
  `llama_model` (weights) from `llama_context` (KV); llama-cpp-python
  0.3.23 has no public second-context API, so `core/models/aux_lane.py`
  builds a normal `Llama` while a scoped constructor patch ADOPTS the
  worker's already-loaded model (0.08s spawn, +0.13 GB, zero re-read of
  the GGUF; full `create_chat_completion` machinery). Alternative
  measured and rejected: `save_state()/load_state()` memcpy costs
  0.7s round-trip at 6K tokens, scales linearly (~2s+ at 20K), and the
  aux call still cold-prefills inside the borrowed context every time.
- **One chokepoint** — `LlamaCppPythonClient.chat()` IS the aux lane;
  every side-channel call already routes through it (persona filter,
  skip-final finalizer, reflection, deep-think plan/digest, memory
  review, goal clarify/eval, ThinkingRunner), so future aux calls can't
  regress the worker KV. The finalizer no longer replays the ~10K-token
  tool schemas (that trick existed only to protect the worker prefix;
  lane separation does it structurally). Fail-open: spawn failure or
  `aux_ctx: 0` degrades to the old shared-context behaviour.
- **Config (HUD-ready, applies on restart)** — `model.ctx` stays the
  worker knob; new `model.aux_ctx` (default 4096, 0 = off) sizes the aux
  lane. Both ride the bridge config query / `save_config` as additive
  `model_ctx` / `model_aux_ctx` keys (pytest-pinned; no Swift shape
  change needed).
- **Acceptance (REAL bridge on jros-dev, persona ON, HAL/jarvis)** —
  operator prompts, wall = send→reply including the filter:
  before (lane off): turn 1 9.9s (ttft 0.33), turn 2 **48.8s (ttft
  45.6)**; after (lane on): turn 1 10.0s (ttft 0.33), turn 2 **5.2s
  (ttft 0.71)**. Persona filter cost ~1.3-2.8s/turn, now off the
  critical prefix. Both turns beat the <10s target; turns 2+ are back
  at the pre-persona 0.3-0.7s TTFT.
- **65K worker ctx (measured for the operator; restored to 32768)** —
  KV buffer 1.75 GiB @32K → 3.5 GiB @65K (+2.1 GB RSS); boot prewarm
  identical (42.6s vs 43.8s); warm turns 1.9-6.2s; synthetic 17K-token
  cold prefill 50.4s @65K. 65K costs ~2 GB RAM and nothing else at
  today's prefix sizes.
- **Bench gate** — full corpus A on E4B: **79/81 (98%), errors=0**
  (run 20260705-195422), equal to the pre-lane baseline — the aux lane
  did not change worker behaviour.

## 2026-07-05 — chat-shell fixes + identity-vs-character standardization (0.6.0) [ux/agentic]

Operator live look-check follow-ups (Swift chat window) + a design decision.

- **Thinking chip is transient** — the Swift chat's "thinking…" chip used to
  persist under every reply; it now behaves like typing dots (removed when
  the turn ends), one chip per turn, id-tracked reply placeholder.
- **Dark-canvas contrast** — the chat window pins itself to `darkAqua`
  (titlebar title was near-black on the dark canvas); composer placeholder
  and mic icon moved off system colours onto the Term palette.
- **Slash commands over the bridge** — the `send` op pre-dispatches a leading
  `/` through the TUI's slash registry (safe read-only subset: help/tools/
  skills/facts/plugins/instance/instances/models/board/config); interactive
  or TUI-bound commands answer with a pointer. Python stays the source of
  truth; the shell renders the returned text.
- **Reply telemetry (protocol v1 additive)** — `reply` frames optionally
  carry `elapsed_s` / `ctx_used` / `ctx_max` (omitted when unknown; absent
  keys keep decoding — pinned in `protocol_v1_fixtures.json` on both the
  pytest and XCTest sides). Swift renders "replied in 3.2s" under each reply
  and "ctx 18.3K/32.8K" in the status bar.
- **`jaeger dev --tui` exit SIGABRT (F1)** — the module entry point
  (`interfaces/tui/__main__.py`) now applies the same flush + `os._exit`
  guard as `main.main()`; the dev launcher execs straight into it, so the
  old guard never ran on that path.
- **Identity vs character (operator decision)** — the AGENT NAME is
  identity.yaml's, always ("a robot like Jarvis, but I will name him Ted");
  the character supplies personality only and never overwrites the name.
  `_identity_name` no longer reads the active character;
  `JAEGER_BENCH_NEUTRAL_IDENTITY` is a no-op (kept for bench-runner
  compat); the persona filter context injects "your name is <identity.name>;
  you embody <character>'s persona". Bridge `identity` query returns
  additive `agent_name`; the Swift chat header/status bar lead with the
  agent name, character as secondary flavor ("Ted · playing HAL 9000").
  The tray card (MenuCard — operator's file) still leads with the
  character: data is exposed, swap is an operator follow-up.
- **Bench gate (framework-prompt change)** — full corpus A on E4B:
  **79/81 (98%)**, errors=0 (run 20260705-182745; fails: mt_file_round_2,
  pf_macos_do). Meets the ≥79 baseline.
- **Activity trace + turn separators (operator keepers)** —
  `display.activity_trace` now also drives the Swift chat's tool/thought
  chips (full/summary/clear/off); new `display.turn_separators` bool gates
  the thin accent rule between turns. Both flow over the bridge config
  query / save_config. HUD picker not built (operator's file).
- **Latency regression MEASURED, not fixed (queued next)** — per-stage
  probe on jros-dev/E4B (~20K-token prefix): with the persona filter ON,
  EVERY turn pays ~41-44s TTFT (full re-prefill — the filter's clean-
  context call evicts the single-slot KV between turns; the filter call
  itself is only 1-5s). With `JAEGER_PERSONA_FILTER=0`, turns 2+ hit the
  KV cache: TTFT 0.3-0.4s, totals 3-14s vs 42-48s. The f6d72fe follow-up
  hypothesis is confirmed; skip-final finalizer likely contributes the
  same way. Fix is the next work item — nothing restructured in this pass.

## 2026-07-01..03 — agentic-quality sprint: persona, scoped surface, skill framework [agentic]

E4B (gemma-4-e4b) accuracy + the tool/skill surface. All bench numbers are the
dev bench (81-case corpus, `dev/benchmark/bench.py`), E4B, headless.

- **Workers run vanilla (persona out of execution)** — an A/B/C bench measured
  persona-in-worker taxing the 4B ~7-10% (vanilla 75.5 vs full 68). Execution
  context is now persona-free; the character-voice output filter is **deferred
  (planned)**, so worker replies currently have no persona voice.
- **Lean scoped tool surface** — `list_tools`/`load_tools`/`describe_tool` +
  a search-before-act mandate let the model scope its own toolset. **Opt-in,
  default OFF** (`JAEGER_TOOLSET_SCOPING=0`). Measured: scoped 73/81 at ~460s
  beats the full 96-tool surface (70) and is ~24% faster — the scaling path,
  not yet the default.
- **Gemma tool-call salvage** — Gemma-4 sometimes drops the closing
  `<tool_call|>` token, stranding a real call as text. `dialects/gemma.py` gained
  a tolerant fallback (only when the strict patterns match nothing).
- **Skill framework overhaul** — all 90 skills scrubbed to an 8-point authoring
  standard (`dev/docs/reality/skill_standard.md`): correct + real tool names, boundary
  descriptions, lean SOPs, lazy-loaded references. New `skill-builder` meta-skill
  (create/review/improve SOP). Tool loader now reads `metadata.jros.tags`.
  Regression caught + fixed: the Tier-2 rewrite subagents were given a tool list
  built from a bare import (missing build-time tools like `delegate_task`) and
  wrongly stripped `delegate_task` from 8 skills — restored.
- **Symmetric tool/skill surface** — `skill`→`list_skills`, `load_toolset`→
  `load_tools`, so it reads `list_tools`+`load_tools` / `list_skills`+`use_skill`.
- **Bench:** E4B unscoped default lands in the **75-77/81** band (a record 77
  before the skill overhaul; 75 after — two borderline cases flip
  deterministically on the changed skill-index prompt: `skill_native_tier` and
  `selfimprove_curate`, both cases where the agent does something defensible the
  scorer doesn't credit). Harness false-negatives were also fixed (4 cases).

**Planned / deferred (NOT done — do not assume shipped):**
- The planning/runner lever that makes a `PLAN:` line OBLIGATE its stated first
  action (recovers `native_tier` + `selfimprove_curate`).
- Two-pass persona voice filter over the vanilla worker output.
- Flipping the scoped surface on by default once the tool library is large enough.
- 26B re-bench on the current stack (only E4B has been exercised lately).

---

## 2026-06-28 — first-run model-download progress [install/update]

The last 0.6 install-experience item — kept simple.

- The **HF path** (`hf_hub_download`, the normal case since `huggingface_hub` is
  present transitively) already gives a tqdm progress bar + ETA + **resume** +
  cache; `download_model` prints the size up front. So the common case was
  already covered.
- The **urllib fallback** (only when `huggingface_hub` is absent) gained a real
  progress bar + speed + ETA via a pure `_progress_line(name, done, total,
  elapsed)` helper (unit-tested). It restarts rather than resumes — the HF path
  is the resume story; the fallback is the no-extra-deps safety net.

Closes the 0.6 install/update/lifecycle theme.

---

## 2026-06-28 — skill evolution Plan C: archive + scoring/retirement + regrouping [agentic]

Plan C (`SKILL_EVOLUTION_PLAN.md` §6–§7) closes the pipeline; the loose core
modules are grouped to match the codebase convention.

- **`core/skill_improvement/`** — `skill_notes`, `skill_revisions`,
  `skill_maintenance` moved into one package (was loose under `core/`), matching
  `core/memory/`, `core/models/`, etc. Imports updated; usage unchanged. The
  trigger + second-person review stay in `agent/background/skill_review.py`
  (they ride the Deep Think loop; core can't depend on that layer).
- **§6 per-skill archive** — `archive_superseded_versions` moves all but the
  newest K `<skill>_vN` into `<instance>/skills/.archive/` (recoverable; the
  loader scans direct children + `_v<N>`, so `.archive/` is invisible). The
  only version history for gitignored instance skills.
- **§7 scoring + retirement** — `skill_score` derives uses/wins/win-rate from
  the notes; `retire` moves a skill to `.archive/` (recoverable) **guarded** so
  only agent-owned (`self-improvement` revision, no `manual`) low-win skills are
  eligible — never a user-written one. `maintenance_sweep` runs both each
  Deep-Think idle cycle. `jaeger skills score` surfaces win-rates + candidates.
- Recoverable + guarded throughout; nothing is ever deleted, core zone untouched.
  6 new tests.

This completes the refined skill-evolution pipeline: structured summaries →
probabilistic idle trigger → second-person measured review → archive + retire.

---

## 2026-06-28 — skill evolution Plan B: the second-person review [agentic]

Plan B of the refined design (`SKILL_EVOLUTION_PLAN.md` §3, + prompt-level
§4/§5) — the centerpiece.

- **`_summaries_block`** renders a skill's accrued structured summaries (since
  the last review) as the trajectory the auditor reads cold.
- **`review_description` rewritten into a second-person audit** — "review your
  own logged uses AS IF THEY WERE SOMEONE ELSE'S": a 6-step audit (objective ·
  issues · step economy · guess-vs-verify · THE ONE LESSON as an imperative ·
  edit/new/nothing) with the honesty rule (no imperative → change nothing).
  Then MEASURED application: benchmarkable → keep-if-better/revert; pure
  playbook → apply (scored later); no-fit → spawn a new skill (dedup: prefer
  EDIT). The grammatical distance is the point — it encodes *what should change*
  rather than *what happened*.
- §4 validation + §5 spawn-new are **directed by this prompt** (executed with
  the existing `benchmark_skill`/`reload_skills`/`file_write`/
  `record_skill_revision` tools); the scoring tally + retirement land in Plan C.
- 5 new/updated tests.

---

## 2026-06-27 — skill evolution Plan A: structured summary + probabilistic trigger [agentic]

Plan A of the refined skill-evolution design (`SKILL_EVOLUTION_PLAN.md`
Refinement §1–§2), layered on the shipped base loop.

- **Structured post-use summary** — `SkillNote` / the `skill_note` tool widened
  from a one-liner to `{objective, calls, procedure, errors, flag}`
  (backward-compatible; old journal lines still load on defaults).
- **Probabilistic severity-weighted trigger** (`agent/background/skill_review.py`):
  `activation` = severity-weighted sum since the last review (`smooth 0 · slow 1
  · issues 2 · failed 3`; a `flag` adds +4); `fire_probability` = sigmoid with a
  **gate** (`S<S_min→0`) + **ceiling** (`S≥S_max→1`); `select_for_review` fires
  probabilistically, worst-first, capped at `K`. A `sweep` runs each Deep-Think
  idle cycle — proposes the selected skills and logs `S/P/fired` to
  `skill_review_log.jsonl`; a `flag`ged note fast-tracks one. Replaces the old
  eager count-threshold on-note trigger.
- Randomness is only in *scheduling*; the keep/kill decision stays measured
  (unchanged). 8 new/updated tests.

Next: Plan B (second-person review + validation + spawn-new) · Plan C (per-skill
archive + scoring/retirement).

---

## 2026-06-27 — update channels + install.sh toolchain mirror [install/update]

Two minor 0.6 loose ends.

- **`jaeger update --channel {stable,latest}`** — stable = newest release tag
  (default); latest = `master` / development HEAD. `--ref` pins an exact
  tag/branch/sha and overrides the channel; `$JAEGER_REF` is honoured when
  neither is set (`_resolve_ref`). The archive URL switched to the general
  `/archive/<ref>.tar.gz` form so a branch (master) is fetchable — verified
  HTTP 200 for both `0.5.2` and `master`.
- **`install.sh`** now mirrors the C-toolchain check from `scripts/install.sh`
  (macOS `xcode-select -p`; Linux `cc/gcc/clang`) for the direct `./install.sh`
  path (manual clone), not just the curl bootstrap.

1 new test (`_resolve_ref` precedence); gate green.

---

## 2026-06-27 — in-app update action: reusable UpdateBanner widget [install/update]

The in-app update went from notice-only to a real **action**, packaged as a
**reusable Qt widget** any window can drop in.

- **`interfaces/pyside6/widgets/update_banner.py`** — `UpdateBanner(QFrame)`:
  self-checks off-thread on `start()` (auto), reveals only on a newer release,
  and its **Update now** button opens `UpdateDialog`, which runs `jaeger update`
  via `QProcess`, streams the download/apply output, and prompts to restart.
  Knobs: `auto_start` (check on construct) and `run_default` (built-in action
  vs. host-driven via the `updateRequested` signal). `set_status(dict)` lets a
  host/test feed status directly.
- **Jaeger Studio now hosts the widget** — the bespoke banner (`_UpdateCheckThread`
  / `_make_update_banner` / `_on_update_status`) was removed in favour of
  `UpdateBanner(self)`. Any future Qt window adds it the same one-line way.
- 7 new tests (reveal logic + the click contract, offscreen). The `QProcess`
  update run is a GUI-spawn path, not headless-verified.

---

## 2026-06-27 — install-experience polish: prereq detection + doctor FDA [install/update]

Two low-risk 0.6 install-experience items.

- **Installer prereq detection** (`scripts/install.sh`) — beyond git + Python it
  now checks a **C toolchain** (macOS `xcode-select -p`; Linux `cc/gcc/clang`)
  and hard-fails early with the exact per-OS fix (no half-built `.venv`);
  **PortAudio** is a non-fatal Linux warning (`libportaudio2`).
- **`jaeger doctor` Full Disk Access** (`core/diagnostics/doctor.py`) — a
  macOS-only Check that probes a TCC-gated path; when FDA isn't granted it
  points to System Settings → Privacy → Full Disk Access (informational — FDA
  matters only for protected folders, so never a hard failure).
- Post-install next-steps already corrected to the `jaeger agent` surface.

3 new tests (FDA on/off/undeterminable + off-macOS skip).

---

## 2026-06-27 — Mac launcher + in-app update surface [install/update]

The "feels like a real app" polish + the update surface that pairs with
`jaeger update`.

- **`jaeger launcher install|remove`** (`cli/verbs/launcher_verb.py`) — a thin
  `/Applications/Jaeger.app` (`Contents/MacOS/Jaeger` stub execs the install's
  `jaeger`; `Info.plist`; `lsregister`). Created locally → no quarantine /
  Gatekeeper prompt, no signing. Falls back to `~/Applications` when
  `/Applications` isn't writable. install.sh next-steps now offer it (+ an
  autostart hint, OS-aware).
- **In-app "update available"** via the shared `version_check.update_status()`:
  - tray: a "Check for Updates…" item (checks on click, notifies the result —
    not on every menu open, which would block on the network);
  - Jaeger Studio: a top banner that auto-checks off the main thread on window
    open (`_UpdateCheckThread` → `_on_update_status`) and shows the newer tag.
- Verified: the launcher bundle was built in scratch + `plutil -lint` OK; the
  Studio banner show/hide tested offscreen; 15 new tests. (The live rumps
  notification + double-clicking the real `.app` are macOS-GUI paths, not
  headless-verifiable.)

---

## 2026-06-27 — operator term: instance → agent (surface only) [ux]

Operators were managing "instances" — vague ("instance of what?"). The
operator-facing word is now **agent**: a deployed AI that plays a *character*,
with its own memory/config/model. **Surface-only** by choice — internal
`InstanceLayout` / `.jaeger_os/instances/` is unchanged (and "agent" already
names the runtime loop, so renaming internals would collide).

- **`jaeger agent <create|list|use|inspect|delete|clear>`** — one unified
  command (`instance_verbs._cmd_agent_argv`): `create` runs the wizard (friendly
  positional name → `--name`), the rest delegate to the instance verbs. Unifies
  the old `setup` + `instance` + `instances` surface.
- **`--agent`** added as an alias of `--instance` (main run path + skill /
  memory / migrate verbs); `dest` stays `instance`, so every internal read is
  unchanged.
- `jaeger instance` / `jaeger setup` / `--instance` kept as quiet aliases —
  nothing breaks. README operator examples updated.
- Per-agent reset stays `jaeger agent clear` / `delete` (existing verbs); this
  is purely the operator vocabulary.

---

## 2026-06-27 — `jaeger uninstall` + `jaeger reinstall` [install/update]

Closes the lifecycle: install → run → update → **reinstall / uninstall**.

- **`jaeger uninstall [--purge] [--yes]`** (`cli/verbs/uninstall_verb.py`) —
  removes the framework (the product allowlist + `.venv` + the updater's
  scratch/rollback dirs); **keeps `.jaeger_os/`** (every agent) unless
  `--purge`. **Refuses on a dev clone** (`.git` at the root — never nuke a
  working checkout); non-interactive refuses without `--yes`. The destructive
  + guard paths are unit-tested, and the dev-clone refusal was walked live on
  this repo (exit 2, nothing removed).
- **`jaeger reinstall [--ref TAG]`** (`update_verb._cmd_reinstall_argv`) — clean
  reinstall keeping agents. Clean install → `_update_download(force=True)`
  (re-fetch the product even at the same version + always resync deps); dev
  clone → repair the editable install (`uv pip install -e .`). Recovers a
  broken/half-updated install — the gap the curl installer left (it *reuses*
  `.venv`). Per-agent reset already exists (`jaeger instance clear`/`delete`),
  so this is framework-level by design.

---

## 2026-06-26 — `jaeger autostart` + install/update polish [install/update]

Completes "units running unattended" + the cheap theme wins.

- **`jaeger autostart enable|disable|status`** (`cli/verbs/autostart_verb.py`)
  — opt-in boot/login service. macOS writes/loads a `~/Library/LaunchAgents/`
  LaunchAgent (`launchctl load -w`); Linux writes a `systemd --user` unit
  (`enable --now` + best-effort `loginctl enable-linger` so it comes up at boot
  without an interactive login — the robot/appliance case). Runs the install's
  `jaeger` (venv console script, else the `./jaeger` wrapper); extra args
  forwarded. Manual `jaeger` start is unchanged. Pure service-file builders +
  routing unit-tested (7); launchctl/systemctl IO not OS-tested.
- **Lighter update download** — `.gitattributes export-ignore dev/` + `.github/`
  trims the git-archive tarball `jaeger update` fetches (verified via
  `git archive --worktree-attributes`: `dev/`/`.github/` drop, `jaeger_os/`
  stays).
- **README accuracy** — `jaeger` documented as the canonical command (Quick
  Start + Daily-use; `run.sh` kept as alias), `jaeger update` upgrade path
  (was the wrong `git pull && ./install.sh`), wizard character-pick, badge
  0.3.0 → 0.5.2. (The broader `0.3.0`-era Status narrative still needs a
  content pass — flagged, not silently half-fixed.)

---

## 2026-06-26 — `jaeger update`: clean-install download/apply [install/update]

The install/update theme's headline lands its core. A clean curl/product
install has no `.git`, so the old `jaeger update` (git pull) couldn't update it
— it now **downloads the target release tarball and swaps the product in
place**, keeping `.venv/` + `.jaeger_os/` untouched.

- **`core/version_check.py`** — numeric version parse/compare + `latest_version()`
  (GitHub tags API, degrades to `None` offline). Pure parts unit-tested; shared
  by update + doctor.
- **`update_verb.py`** — no-`.git` install → download tag tarball → copy the
  PRODUCT allowlist → per-item `os.replace` swap (prev kept for rollback) →
  reinstall deps only if `requirements`/`pyproject` changed. `--ref TAG` pins;
  `--rollback` restores the kept previous product (one level). Dev clones keep
  the git-pull + editable-reinstall path.
- **`jaeger doctor`** appends a current-vs-latest line (CLI only — the agent's
  `self_check` stays network-free).
- **Repo hygiene:** untracked `jaeger_os/interfaces/avatar/.build/` (93 MB /
  2189 files of derived Swift cache) that had been dragged into every clone +
  install; `.gitignore` now ignores `.build/` anywhere.
- Walked end-to-end against **real GitHub** (tags API + 0.5.2 tarball download +
  extract, `dev/` correctly excluded) + 16 new unit tests. Remaining theme
  work: in-app update surface, Native Mac app, `jaeger uninstall`, README fixes.

---

## 2026-06-26 — skill self-improvement loop (on by default) [agentic]

Recipe-skills now improve over time, measured. Full design:
`dev/docs/history/SKILL_EVOLUTION_PLAN.md`. **On by default (opt-out via
`set_skill_review(False)`)** — the operator wants the agent to get better with
use; it's safe by construction (sandboxed to `<instance>/skills/`, smoke-gated,
benchmark-validated, revision-logged, append-only rollback).

- **Notes journal** (`core/skill_notes.py`, `skill_note`/`skill_notes`): the
  agent jots a one-line post-use note (smooth/slow/issues/failed) — cheap signal.
- **Review loop** (`agent/background/skill_review.py`): a skill that piles up
  issue/failure notes auto-proposes a Deep Think task (or `request_skill_review`
  by hand). The task runs the MEASURED loop — baseline `benchmark_skill` → write
  `_vN` → re-benchmark → keep only if smoke passes AND delta > 0, else revert.
  Reuses the existing Deep Think runner (no new executor); auto-approves +
  self-applies when enabled (its own switch, not the live-turn autonomy mode).
- **Revision log** (`core/skill_revisions.py`, `record_skill_revision`): the
  `_vN` is the revision id; the log records when/why/delta. `jaeger skills
  notes` + `jaeger skills revisions` surface it.
- Better than the Hermes pattern it's modelled on: notes (cheap, cross-use
  signal) vs raw-turn replay; heavy rewrite runs idle/asleep on the strong
  model, never mid voice-turn; and it's measured, not trusted.

## 2026-06-26 — benchmark: gemma-4 12B + QAT; bench tooling un-rotted [models]

Ran the flat-corpus benchmark (65-case v1.2) on the updated **gemma-4-12B-it-Q4_K_M**
and the new **gemma-4-12B-it-QAT-Q4_0**. **No agent/pipeline regression** —
routing is **57/57 (100%)** on both (vs 98.1% historically). Both score **86.2%
(56/65)**; QAT is the win — equal capability, **smaller (7.0 vs 7.4 GB) and
faster (p50 5.0s vs 6.0s)**.

The Score looks lower than the old leaderboard's 96.6% **only because of a
persona/answer-format effect, not capability**: my bench-instance fix (below)
means the bench now measures the active **jros-dev / Jarvis** persona, whose
formal, comma-formatted numbers (`8,760`, `1,093`) miss the literal
`answer_contains` substring checks (`8760`, `1093`). The model routes + chains
correctly every time; several "fails" are it behaving correctly (declining a
missing file / unknown city). The old 96.6% measured a different (neutral
`default`-instance) persona. *(Open follow-up: the bench's numeric answer checks
should normalise thousands-separators; and the two bench entry points normalise
model names differently — `gemma-4-12b-it-q4-k-m` vs `gemma-4-12B-it-Q4_K_M` —
so one model shows as two leaderboard rows. Neither touched here.)*

**Bench tooling un-rotted** (`run_model_sweep.py`, `run_flat_bench.py`) — a chain
of stale-path/setup bugs from the 0.2.x→0.6 migrations, none from agent code,
all surfaced by trying to run it: the active-instance config path
(`~/.jaeger`/`src/` → the package resolver); `REPO`/`SRC`/`_REPO` off-by-one
(the scripts moved under `dev/` → doubled `dev/dev/...` paths + a nonexistent
`run_flat_bench.py` → 0 cases) → pyproject-marker root; a hardcoded
`instance_name="default"` that benched the wrong instance once the active was
renamed off "default" → the active instance; and **the sweep now forces
`permissions.mode=allow`** during a run so a capability bench auto-approves
tier-gated tools instead of silently failing every file/schedule/multistep case
under a `confirm`-mode instance run headless (config saved + restored around it).

## 2026-06-25 — JROS is an editable package again [packaging]

JROS installs as an **EDITABLE package** (PEP 660), restoring proper packaging
that 0.2.3 dropped (when it cut from `pip install jaeger-os` to clone +
PYTHONPATH) — WITHOUT moving code. `jaeger_os/` stays at the repo root; operator
state stays in `.jaeger_os/` beside it. This is the **Hermes model**
(editable-into-clone), chosen over *flatten* (worse imports, bare `import core`)
and *src-layout* (reverses 0.2.6 + breaks the state-beside-package resolution) —
a self-modifying, stateful agent can't live in read-only site-packages.

- **`pyproject.toml`** — real `[build-system]` (`setuptools.build_meta`) +
  `[project]` (`jaeger-os`, `requires-python = ">=3.11,<3.13"`). Version
  single-sourced from `jaeger_os/__init__.py` (`dynamic` attr); deps
  single-sourced from `requirements.txt` (`dynamic` file). Verified live:
  `pip install -e .` builds the editable wheel; metadata reports 0.5.2 + 37 deps.
- **`install.sh`** — bootstraps `uv` into the `.venv`, then `uv pip install -e .`
  (deps flow from requirements.txt via the dynamic table); falls back to pip
  editable. Curl one-liner + URL unchanged.
- **`jaeger update`** (editable / dev-checkout — the default) now actually
  updates: `git pull --ff-only` + editable reinstall (prefers the venv `uv`).
  Refuses to pull over a dirty tree (prints the manual hint instead).
- **`jaeger --version`** → `jaeger-os 0.5.2`, via the `./jaeger` wrapper.

**Staged — NOT in this commit (planned):** a first-class `jaeger` console-script
entry point. The operator command is still the `./jaeger` bash wrapper, which
dispatches across `jaeger_os.cli` / `.cli.run` / `.interfaces` / `launch.py`; a
single entry point must unify those (`.cli.run` needs an importable `main()`)
and be walked across the voice / dev-TUI / bridge / mcp / agent-run flows before
it can replace the wrapper. Deferred deliberately — a partial entry point would
shadow the working command.

## 2026-06-25 — autonomy modes (ask / scoped / auto) [agentic]

The agent's execution autonomy is now a switchable mode, like the runtime
model-modes — the plan is agreed up front, then it runs without per-action
approval prompts (the philosophy the operator asked for: "ask and plan up front,
then a self-sufficient loop; reach out only if it needs more info").

- **`jaeger_os/core/runtime/autonomy.py`** (new) — `current_autonomy()` /
  `set_autonomy()` / `autonomy_info()`; modes `ask | scoped | auto`, **default
  `scoped`**. Switching is instant (no model swap). Published on `ModeState`
  (new `autonomy` field) for the tray/header.
- **One chokepoint** — `BusConfirmationProvider.confirm()` consults the mode
  after the admin gate: `auto` → approve without prompting; `scoped` → honor
  standing "always" grants, prompt-once for anything new; `ask` → prompt every
  time (ignores grants). Tier-5 DEV_BYPASS still needs human override in every
  mode (it never routes through `confirm`); non-admins still denied upstream.
- **Tools** `set_autonomy` / `get_autonomy` (in the `models` toolset). The
  reach-out valve already existed (`clarify` → routes to the active channel);
  Deep Think already approves-once-runs-to-completion — autonomy only governs
  the per-action prompt.
- **Cross-channel** `/ask` `/scoped` `/auto` (+ `/autonomy [name]`) on
  telegram/discord/imessage via `_messaging.autonomy_command` — admin-gated,
  same rails as `/mode`.
- **Tests:** `dev/tests/jaeger_os/core/test_autonomy.py` — module default/set,
  `confirm()` honoring each mode (auto-approve / scoped-grant / ask-prompts),
  slash parse, tools registered. 4 passing.

## 2026-06-15 — windowed app (Pattern 1) boots through the chassis [core]

JROS's chassis copy (`jaeger_os/app/`) gained the format's Tier-1 **`core`**
role (resynced from `jaeger_app_framework`), and the windowed app now boots
through it instead of a bespoke host:

- **`jaeger_os/app/`** — ported `core.py` (`Core` ABC + `CoreMainThreadError`,
  main-thread-init assertion), `[core]` manifest parsing (`CoreSpec`), the
  `init_core` boot phase (core built on the main thread, after the bus,
  before nodes/surfaces; `core.stop()` before the bus closes), and exports.
  JROS's intentional divergences (no-fcntl lock / `process_slot.py`, simpler
  supervisor, `asyncio`/`tui` event loops) are untouched. **29 conformance
  tests green** (4 new core tests; boot order proven via a bus subscription,
  not a module global — JROS's pytest import layout makes cross-import
  globals two objects).
- **`jaeger_os/agent/loop/agent_core.py`** — `AgentCore(Core)`: folds the old
  `jaeger_os/core/host.py` (deleted) — model boot on the main thread +
  `AgentBridge` + drain-then-cleanup teardown — into the `[core]` role. There
  is now ONE app/host (the chassis); the second `JaegerApp` class is gone.
- **`jaeger.windowed.toml`** — the Pattern-1 manifest (`[core]` + chat window
  + tray, `event_loop = "qt"`, `shell_quits_core = false`). A bare `./launch`
  boots `JaegerApp("jaeger.windowed.toml").run()` via
  `jaeger_os/core/windowed.py`. `./launch --tui` (Pattern 0) is unchanged.
- **chassis fix (upstreamed)** — `JaegerApp.__init__` now honors a manifest
  *file* path (e.g. `jaeger.windowed.toml`), not just a directory's default
  `jaeger.toml`. Fixed in the framework canonical + synced to all copies +
  ported to JROS.

**Runtime status: ◑ partial — headless-verified, GUI walk pending.**
Verified headless (model boot + `run_for_voice` + the Qt loop stubbed):
`JaegerApp("jaeger.windowed.toml").boot()` builds the `AgentCore` on the main
thread, starts the bridge, round-trips `ChatMessage → ChatReply` over the
chassis bus, and drains + cleans up the model on shutdown
(`test_windowed_app.py::test_windowed_manifest_boots_agent_core_over_chassis`).
1559 tests green across app/agent/core/interfaces. **NOT yet runtime-walked**:
a real `./launch` — actual model load, the Qt window + menu-bar tray
appearing, a live chat turn, and tray-persist-on-window-close — needs the
operator's machine (model weights + a display).

## Findings & fixes — 2026-06-12 hardware framework + JP01 sim package (0.5.0)

Implements dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md §4.2 steps 1+2.
Everything below is unit-tested (56 new tests, all headless against
MockTransport); **nothing has touched real hardware** — every JP01
controller ships `simulated: true` and the capability tools are
beta-gated (`JAEGER_DEV_MODE=1` to see them) until live-walked.

- **`jaeger_os/hardware/` framework** — `Transport` ABC
  (`SerialTransport` lazy-pyserial, `ZmqReqTransport` with the JP01
  relay target-wrapping + REQ reopen-on-timeout, `MockTransport`);
  `Protocol` ABC (`AsciiBracketProtocol` — the JP01
  `HEADER[payload]\n` dialect with partial-line buffering +
  heartbeat classification; `JsonLineProtocol`); `Link` =
  Transport × Protocol with primary→relay fallback and a
  crash-proof RX reader thread; `load_package` — topology.yaml →
  msgspec-validated `PackageSpec` (unknown fields, dangling
  controller refs, dotless capability names, bad estop scopes, and
  `requires_framework` version mismatches all refuse loudly at load).
- **Capabilities → ordinary tools** — `register_package_capabilities`
  groups `subsystem.action` capabilities into per-subsystem umbrella
  tools (kanban/memory precedent). Dispatch order per call:
  permission tier → e-stop latch (HARDWARE-tier actions fail closed;
  reads and lights keep working; `allow_when_latched` exempts
  `motion.stop`) → link health (offline = typed retryable error +
  `check_fn` hides the tool) → per-action Pydantic validation →
  handler. Nothing raises into the agent loop.
- **Safety** — `/act/estop` latched topic (`EStop` struct) +
  `EStopLatch`: any bus publisher latches; registered node-local L1
  stops run once on engage; release is operator-only (non-operator
  `engaged=False` on the wire is ignored). `/sense/node_health`
  (`NodeHealth`) published at 1 Hz per controller by the package
  runtime. Both structs registered in `TOPIC_TO_CLASS`.
- **Permissions change** — tier 3 (HARDWARE) no longer hard-denies:
  it routes through the confirmation provider like tiers 1/2/4. The
  old unconditional deny was a leftover from the module's
  Lilith-on-a-laptop origin ("reserved for JROS" — this IS JROS).
  Fail-safe unchanged: no provider wired → `DenyAllProvider` refuses.
- **JP01 package** (`hardware/packages/jp01/`) — topology.yaml with
  surveyed truth (ports, bauds, Jetson relay path, no-IMU,
  no-L0-watchdog warning flag); MC01/AVC01/VCC01 adapters that
  implement the generic node Protocols (stock `MotorNode`/`LightNode`
  drive them from `/act/motion`//`/act/light`) plus capability verbs
  and an L1 `estop()`; firmware-shaped `simulator()` responders;
  near-verbatim `devices/` builder ports; `boot.py` resolving the
  topology's `adapter:` refs (declared = wired — no parallel map),
  with atexit teardown that neutralizes motors + blanks LEDs.
- **Agent surface** — `motion` / `lights` / `robot_vision` /
  `telemetry` umbrella tools; `motion.stop` = MM[0,0,0] + L2 latch
  (the agent can always stop, only the operator un-stops).
  `config.yaml: hardware.package: jp01` boots it (warm-job,
  best-effort, degrades per-controller).
- Suite: **2,182 passed** (+57). Pre-existing skips unchanged
  (lilith-face Mochi backdrop, process-slot flake).

---

## Findings & fixes — 2026-06-12 VoiceLLM-updates port (0.5.0)

VoiceLLM (the end-to-end voice testbed) shipped its own review fixes
recently; this pass harvests the ones JROS's voice pipeline needed.
Unit-tested (26 new across voice + MLX tests); **the VAD-behaviour
changes especially need a live mic walk**.

- **MLX stop-marker holdback** — TODAY'S new JROS MLX adapter emitted
  deltas before stop-scanning, so a marker split across two chunks
  ("<|im_" + "end|>") would leak its head into the delta stream — TTS
  reads "<end_of" aloud (VoiceLLM hit exactly this with Kokoro).
  Ported `_scan_stream_text`: text is emitted only once it can no
  longer be a marker prefix; held-back text flushes at stream end.
  Also ported: sampling now builds a proper ``sampler=`` via
  ``make_sampler`` (bare ``temp=`` kwargs silently diverge or
  TypeError on mlx-lm ≥0.21), warning loudly on fallback.
- **Honest voice latency** — JROS had NO speech-end timestamp
  anywhere (the entire listen+STT phase was invisible; flagged in the
  first review). Now: the VAD worker stamps ``speech_end`` the moment
  the silence hangover closes the phrase, ``next_phrase`` stamps
  ``stt_done`` after the accurate pass, both ride the ``Transcript``
  message (new ``speech_end_pc``/``stt_done_pc`` fields, 0.0 =
  unknown), and the voice loop prints + logs
  ``[voice-latency] stt=… agent=… speech-end→speak=…`` right before
  TTS — the number the operator actually FEELS, measured end to end.
- **Short-phrase early commit** — quick utterances ("yes please",
  "good night") commit after 350 ms of silence instead of the full
  700 ms hangover (phrases ≤1.5 s of voiced speech; ``short_phrase_
  max_ms=0`` disables). Direct port of a VoiceLLM operator-feedback
  fix; ~40% snappier on exactly the turns where lag is most felt.
- **Farewell detection** — "good night" exchanges no longer re-open
  the follow-up window to transcribe scissors. BOTH sides must
  mirror (user farewell AND reply acknowledges) before the follow-up
  is suppressed; STT stays on, next real utterance resumes normally.
  New ``core/voice/farewell.py`` (16 patterns).
- **(REMOVED 2026-06-16) Ignored turns no longer re-arm the follow-up
  window** — this and the entire LLM ``<reply>``/``<ignore>`` voice
  gate were removed.  The gate lived in the agent's system prompt, so
  one model did both gatekeeping and tool-calling, and the gate framing
  suppressed tool routing (gemma-4-26B-A4B: 0/3 tool prompts gated on,
  3/3 off).  The agent is now transport-agnostic; ambient filtering is
  VAD + wake word in the voice input layer.  See CHANGELOG `0.5.0`.
- **♪/*-wrapped hallucination ingress filter** — "♪ music ♪" /
  "*coughs*" forms now drop at the non-speech filter (the
  bracket/paren filter didn't cover them).
- **Verified, no port needed:** JROS already pauses the mic
  SYNCHRONOUSLY before TTS (VoiceLLM's bus-round-trip echo race never
  existed here); context-overflow turns already reach TTS as
  speakable text; the ZMQ bus was already real pub/sub.

---

## Findings & fixes — 2026-06-12 MLX-parity pass (0.5.0)

Operator-reported from the first MLX attempt: "didn't call tools
correctly" and "didn't end the loop early when completed, so it lagged
llama.cpp". Both root causes found and fixed; 14 regression tests.
**Needs a live walk with a real MLX model before trusting** (the
streaming loop is exercised against a faked ``mlx_lm`` in tests).

- **Root cause #1 (tools)** — the old ``MLXAdapter`` inherited
  ``HermesXMLAdapter``: EVERY model got hardcoded ChatML markers and
  Hermes-XML tool prose regardless of its training dialect. Rebuilt as
  a sibling of ``LocalLlamaAdapter``: prompt renders through the
  model's OWN chat template (``tokenizer.apply_chat_template``), tools
  present in the model's native dialect (``detect_family`` +
  ``render_tools_for`` + ``textify_tool_history``), with the Hermes
  block as fallback for unknown families (MLX has no structured tools
  channel — the model must ALWAYS see tools somehow). Parse pipeline
  now matches llama.cpp's: think-block strip, drift extraction,
  envelope cleanup, thinking-exhaustion tagging.
- **Root cause #2 (lag)** — ``mlx_lm.generate`` has no ``stop``
  parameter and the old adapter dropped stop sequences, so every call
  ran out the full 4096-token budget after the answer finished.
  Generation now runs ``mlx_lm.stream_generate`` under our own loop:
  stops the moment the family's end-of-turn marker appears
  (``<|im_end|>`` / ``<|eot_id|>`` / ``<end_of_turn>`` / ``</s>``),
  feeds the per-token progress beacon (true no-token-gap stall
  watchdog + real TTFT), emits ``on_delta`` for live consumers, and
  honours interrupts at token boundaries (a pull-based generator
  break is a clean stop — no llama.cpp-style abort flag needed).
- **Bridge wiring** — ``model.backend: mlx_lm`` previously hit the
  bridge's RuntimeError: ``_adapter_for_client`` only knew llama/
  external client shapes, so the MLX backend could not reach the
  agent loop at all post-cutover. It now detects ``MlxClient`` and
  reuses the client's already-loaded model+tokenizer pair (weights
  load once). In-process stall default (120s) applies to MLX like
  llama.cpp.
- **Install + picker integration** — ``mlx-lm`` installed in the venv
  (0.31.3; ``stream_generate`` / ``GenerationResponse`` surfaces
  verified against the adapter) and added to ``requirements.txt``
  behind a Darwin/arm64 platform marker so Linux installs skip it.
  ``/model list`` now shows a **Local MLX models** section (the
  ``discover_local_mlx`` scan existed but was never rendered);
  ``/model use mlx <name>`` switches to the MLX backend (sets
  ``model.backend: mlx_lm`` + the model directory, auto-selects when
  exactly one MLX model is on disk); ``/model use local`` explicitly
  resets ``backend: llama_cpp_python`` (previously switching
  mlx → local would leave the MLX engine pointed at a .gguf); the
  post-switch fallback truth-check treats mlx as a local target so
  it no longer mis-warns. 3 picker tests.

---

## Findings & fixes — 2026-06-12 Hermes-tail pass (0.5.0)

The remaining adoptable Hermes items, operator-approved. Unit-tested
(539 agent+memory+bench tests, 13 new); live walk pending.

- **Cross-restart session continuity** — the clean-slate rule STANDS
  (raw replay bled stale tasks; that fix is preserved). A freshly
  built session agent is instead seeded with one bounded
  `[PREVIOUS SESSION — REFERENCE ONLY]` digest of that session key's
  recent episodic turns (new `mem.recent_qa_pairs` reads the
  human-facing `answer` column) — orientation without task-state
  replay, same anti-stale framing as compaction digests. Kill switch:
  `JAEGER_SESSION_RESUME=0`. Full-fidelity transcript persistence
  (Hermes `hermes_state.py` style) remains future work and would need
  its own design pass.
- **Token deltas to live consumers** — `AgentCallbacks.stream_delta`
  (declared since Phase 5, never wired) now receives text deltas from
  both HTTP adapters as they stream; the loop passes the callback only
  when a listener is installed. The TTS sentence-chunker can now start
  speaking before the answer finishes — CONSUMING the deltas is the
  voice review's work; the agent side is ready. Local in-process llama
  doesn't stream deltas yet (facade is non-streaming; voice review).
- **Partial-stream recovery** — a connection that dies mid-answer
  after text arrived returns the accumulated text
  (`finish_reason="partial_stream"`) instead of burning a retry on
  words the user may have already seen/heard. A half-assembled TOOL
  call always re-raises — truncated arguments never dispatch.
- **File-mutation verifier footer** — failed `write_file` / `patch` /
  `append_file` / `delete_file` calls that were never superseded by a
  later success on the same target append a warning footer to the
  final answer, catching "I've updated the file!" claims over failed
  writes.
- **Thinking-exhaustion detection** — a local reasoning model that
  spends its whole output budget inside `<think>` is now tagged
  (`finish_reason="thinking_exhausted"`) and surfaced plainly in one
  step, instead of entering the continuation-nudge path (which just
  bought more thinking).
- **Reactive compact-on-overflow** — when a SERVER rejects a prompt
  the estimator thought fit (LM Studio/Ollama/llama.cpp 400 wordings),
  the loop tightens the estimator, re-runs the pre-flight trim, and
  retries the SAME adapter once — previously it walked the fallback
  chain with the identical oversized prompt. The calibrator relaxes
  the ratio back from real usage afterwards.

---

## Findings & fixes — 2026-06-12 memory / latency / bench pass (0.5.0)

Unit-tested (526 agent+bench tests, 12 new); live walk pending.

**Memory — from archive to learning (the Hermes-gap fixes):**
- **Known-facts snapshot in the system prompt** — each session agent
  is built with a bounded (≤1.4K chars) block of curated facts,
  user/preference categories first, frozen at construction so the
  prompt stays byte-stable for prefix caching. The agent now KNOWS
  what it remembered instead of only finding what it thinks to
  search for. New facts surface next session.
- **Background memory review** — every 8 operator turns
  (`JAEGER_MEMORY_REVIEW_EVERY`, 0 = off) a daemon thread runs ONE
  bounded model call over the recent transcript and promotes durable
  signals ("call me Jon", "keep answers short") into the facts store
  (≤5 per review, dedup-checked, audit-logged). Polite by
  construction: takes `llm_lock` only if it's free RIGHT NOW — it
  never queues behind (so never delays) a live voice turn; on
  contention it re-arms for after the next turn. Skips deepthink /
  bench sessions.

**Realtime latency:**
- **Real TTFT end-to-end** — `CallProgress` records its first touch;
  all three adapters report `last_ttft_s` (cloud: first stream chunk;
  local: first sampled token ≈ prefill time); the turn carries it
  through `drive_one_turn` into `LatencyReport.decision_ttft`, which
  was a hardcoded 0.0 (data-as-fiction since Phase 6). The "feels
  slower than VoiceLLM" question is now answerable from JROS's own
  numbers.
- **Tool-prose render cache** (LocalLlamaAdapter) — the per-call
  JSON-serialisation of every tool schema into the system prompt is
  now cached keyed by (dialect family, tool names); recomputed only
  when the visible toolset actually changes.
- (Carried from earlier passes, same goal: parallel all-read
  dispatch, prompt-stable facts snapshot, calibrated estimator =
  fewer needless trims, streaming transport = no false stall kills.)

**Benchmark v1.2 — systematic loop-health testing:**
- **Every bench row now carries loop telemetry**: real `ttft_s`,
  `halt_reason`, `iterations`, `skipped_final`. Summary aggregates
  TTFT avg/p50/p95, a halt-reason histogram (a healthy run is ~empty
  — growth is a loop regression even when pass-rate holds), avg
  iterations, and skip-final counts. The bench now measures the
  LOOP, not just the answers.
- **+6 corpus cases**: two 4-tool ordered chains (old ceiling was
  2-3), two parallel all-read batches (tag `parallel` — the latency
  trend shows the concurrent-dispatch win), and a cross-SESSION
  memory pair (fact stored in one session must surface in a FRESH
  session via the facts snapshot or recall — the end-to-end "robot
  actually knows" test). `BENCHMARK_VERSION = "1.2"`.
- Known coverage gaps that need harness mechanics (not just cases),
  deliberately deferred: fault-injection (mock adapters for fallback
  / empty-response paths — covered today by 526 unit tests), mid-turn
  interrupt/steer timing (async harness), context-compaction
  longevity (synthetic 100-turn session builder). Listed in the
  bench-map report; next bench iteration.

---

## Findings & fixes — 2026-06-12 robot-hardening pass (0.5.0)

Operator-directed follow-up to the Hermes-adoption pass. All
unit-tested (488 agent tests, 7 new); live walk pending.

**Parallel tool dispatch (+ its prerequisites):**
- `ToolDef.side_effect` default flipped `"read"` → `""` (unclassified
  = conservative). The old default silently classified EVERY
  unannotated tool as side-effect-free — parallel dispatch would have
  run `speak` concurrently, and the earlier dedup/no-progress gates
  were quietly over-broad. Both registration decorators accept
  `side_effect=`; 21 read-only builtins in `main.py` are annotated
  `side_effect="read"`; `describe_tool` shows "(unclassified)".
- All-read batches (>1 call, every tool explicitly read, none
  interactive) now execute on a thread pool (≤4 workers) — wall-clock
  becomes the slowest call instead of the sum. Prepare/finish stay
  serial and ordered (counters, callbacks, transcript); only the tool
  functions run concurrently. Mixed batches stay fully sequential.
- Locks added around the listen (Whisper) and vision
  (Moondream/SDXL) model-cache singletons — load/swap is atomic
  under multi-instance dispatch. `browser` stays unclassified
  (sequential) by design.

**Mid-turn steer (operator request):**
- `agent.steer(text)` queues guidance into the RUNNING turn; drained
  as a real user message before the next model step. Persists in
  history (it IS user content). `main.steer_active_turn(text)` is the
  process-level hook beside `request_turn_cancel()` — cancel kills,
  steer redirects. Voice/TUI wiring is the voice review's job; the
  mechanism + hook are ready.

**Deep-think LLM compaction digest (operator request):**
- `ContextGuard(summarizer=…)` upgrades stage-2 compaction to an
  LLM-written digest with deterministic fallback on ANY failure.
  Wired ONLY for `deepthink_*` sessions in `main.py` (bounded
  `client.chat`, 400 tokens) — background work where the extra call
  is latency-free. Voice/chat sessions keep the zero-latency
  deterministic digest.

**Memory-system verdict (operator asked to double-check "similar to
Hermes"):** it is NOT similar — JROS is an audit/recall system
(SQLite facts + episodic log + embeddings, retrieval only when the
model explicitly calls `recall`/`search_memory`), Hermes is a
learning system (curated MEMORY.md injected into the system prompt
every session + a background review agent every N turns that promotes
conversational signals into memory). JROS's storage is actually
richer; the gaps are (1) no fact snapshot in the system prompt —
the agent only knows what it thinks to search for, (2) no periodic
background review promoting episodic signals into facts, (3) no
hook from the tool-call audit into fact promotion. Items 1-2 are the
recommended next memory work (not implemented this pass — needs its
own focused treatment).

---

## Findings & fixes — 2026-06-11/12 Hermes-adoption pass (0.5.0)

Side-by-side review of the Hermes agent (the loop's design ancestor,
clean install) against `jaeger_os/agent/` — four deep-dive studies
(loop lifecycle, context compression, tool execution + error taxonomy,
perf + state). Adopted mechanisms below are **unit-tested** (465 agent
tests, 16 new in `test_hermes_adoption.py`); live walk pending.

**Adopted — context (the daily-driver longevity work):**
- **3-stage compaction** replaces drop-only trimming. Stage 1 prunes
  OLD tool-result bodies to one-line stubs (keeping the on-disk
  artifact path, so spilled results stay reachable via `read_file`);
  stage 2 folds dropped turns into one `[EARLIER CONTEXT — REFERENCE
  ONLY]` digest (user asks / tools used / errors hit — deterministic,
  no LLM call, no added voice latency; re-compactions fold the prior
  digest instead of stacking); stage 3 is the typed overflow as
  before. Usually stage 1 alone fits the prompt and ZERO turns are
  lost where all of them used to vanish.
- **Estimator calibration from real usage** — the guard's
  chars-per-token ratio tightens toward the model's actual tokenizer
  each call (EMA, 10% conservative bias, hard clamps), cutting
  needless trims. Calibration data comes from per-call usage, which
  also exposed a real bug: **Anthropic usage was never accumulated**
  (the loop only read dict-shaped `raw`; Anthropic returns a typed
  object) and cache read/write tokens were ignored — both fixed.

**Adopted — loop behaviour (accuracy on weak local models):**
- **Warn-before-halt** — the backstop now injects recovery guidance
  into the tool result one step before halting (incl. "do not abandon
  tools"); halt thresholds unchanged for bench parity.
- **Result-hash no-progress** — identical READ calls only count
  toward the halt when the result is also identical; polling with
  changing results no longer false-halts.
- **Post-tool empty-response nudge** — one synthetic retry when the
  model goes silent right after tool results (classic Qwen/GLM
  stall); the nudge never persists in history.
- **Wind-down grace call** — at max_iterations the agent spends ONE
  toolless call asking the model to summarise progress instead of
  returning `[halted: hit max_iterations]`.
- **Read-batch dedup** — identical read calls inside one assistant
  message dispatch once; every call id still gets a result.

**Adopted — transport + parsing:**
- **Error-classified adapter chain** — exceptions classify via
  `cloud_errors`; rate-limit/transient retry the SAME adapter with
  jittered backoff (interrupt-aware sleeps) before falling back;
  auth/not-found skip straight to fallback. Previously ANY exception
  caused an immediate provider switch. (`retry_utils` was
  exported-but-unused until now.)
- **Surrogate scrub** before every model call — lone UTF-16
  surrogates (clipboard pastes, byte-level reasoning models) crash
  `json.dumps` in provider SDKs on every later call once they enter
  history.
- **Arg-repair upgrades** — bracket-balancing recovers truncated tool
  calls (`{"path": "x", "content": "ab…` cut mid-string); control-char
  escaping handles llama.cpp builds that emit literal tabs/newlines
  alongside other malformations.

**Evaluated, deliberately NOT adopted (with reasons):**
- **Parallel tool dispatch** (Hermes: 8-worker pool + path-overlap
  gating, ~30-50% latency win on multi-tool turns) — BLOCKED on the
  tool-layer singletons (`vision`/`listen`/`browser` module state);
  parallel dispatch would activate those races. Adopt after per-tool
  locks land.
- **LLM-summarised compression** (Hermes stage 2 uses an aux-model
  call, 5-15s) — mid-turn latency spike is wrong for voice; the
  deterministic digest covers the 80% case. Revisit as a between-turns
  background pass if digest quality proves insufficient.
- **Session persistence / parent-session chains** (`hermes_state.py`,
  SQLite + FTS) — real feature gap (restart loses conversation) but
  it's daemon/state architecture, which needs a plan + operator
  approval first.
- **Mid-turn /steer injection** — voice-pipeline review territory.
- Credential pools, provider-specific recoveries (Bedrock/Codex/
  OAuth tiers), image shrinking — not applicable to JROS's provider
  set today.

---

## Findings & fixes — 2026-06-11 agent-loop reliability review (0.5.0)

VoiceLLM-analog hunt over `jaeger_os/agent/` (loop + adapters). All
fixes below are **unit-tested** (445 agent tests passing, 13 new);
**live voice/model walk still pending** — do not call these
operator-verified until a real session exercises them.

**Fixed — silent-permanent-failure class (the operator's #1 bug class):**
- **Poisoned-transcript repair** — `run_turn` now leaves `messages`
  well-formed on EVERY exit path. Previously: an interrupt or backstop
  halt mid-dispatch left assistant `tool_calls` with no tool results,
  and any adapter exception left an orphaned user message — cloud
  providers then 400 on *every* subsequent turn of the session
  (deterministic re-fail until restart). Un-dispatched calls now get
  synthetic "not executed" results; failed turns append a visible
  `[turn failed: …]` note before re-raising.
- **Pre-flight `ContextOverflow` rollback** — the user message is
  popped before the typed error propagates, so an un-trimmable prompt
  isn't sticky. Mid-turn overflow now halts cleanly with a speakable
  explanation instead of raising through the bridge.
- **Empty assistant responses** (no text, no calls) store a
  placeholder instead of an empty message — Anthropic rejects empty
  text blocks on every later call.
- **Pair-aware history clamp** (`main.py`) — the per-session trim now
  drops assistant-tool groups together instead of blind head deletion
  that could orphan tool results (same 400-forever class).

**Fixed — interrupt + watchdog semantics:**
- **Local barge-in works mid-decode** — `LocalLlamaAdapter.call` was
  swapping the real interrupt event for an uncancellable dummy, so a
  voice interrupt did nothing until the generation completed (minutes
  on a reasoning model). The cooperative abort (logits-processor flag
  + join + context reset) now serves interrupts too.
- **Stale detector measures silence, not duration** —
  `interruptible_call` previously timed out on *total elapsed*, so the
  30s HTTP default killed every long answer (and billed it). Adapters
  now report progress: Anthropic + OpenAI-compat stream at the
  transport level (chunks touch a `CallProgress` beacon; the loop
  still gets one whole message), local llama touches it per decoded
  token. Interrupts mid-stream close the HTTP stream — the provider
  actually stops generating.
- **`OpenAIAdapter(streaming=True)` removed** — it sent `stream=True`
  and then parsed the stream object as an empty message (silent total
  failure). Transport streaming replaced it.
- **Per-tool-result cap scales with ctx** — the fixed 24K-char cap
  exceeded the entire prompt budget at ctx=8192; one big `run_shell`
  result could overflow the window mid-turn.
- **Turn-scoped halt text** — an interrupted turn no longer re-speaks
  the *previous* turn's answer; the per-turn message slice survives
  mid-turn history trims (the bridge previously sliced by stale index
  and could lose the whole turn from session history).
- **Mid-session tool registration** — the dispatch map refreshes per
  turn, so a skill activated mid-session becomes dispatchable without
  rebuilding the agent (the comment that claimed this existed pointed
  at a phantom method).

**Added — beta tool gating (operator request, 2026-06-11):**
- ``ToolDef.beta`` + ``JAEGER_DEV_MODE`` env gate (``./launch --dev``
  sets it). Beta tools are
  excluded from the agent's catalogue — invisible to the model AND
  undispatchable — unless dev mode is on, so half-tested tools can't
  break a daily-driver session. Both registration decorators accept
  ``beta=True``; explicit ``tools=[...]`` allowlists bypass the gate;
  the gate re-evaluates per turn (no rebuild needed to flip);
  ``describe_tool`` reports the flag. First users:
  ``set_avatar_state`` + ``play_timeline`` are now actually
  registered as agent tools (commit f768fb7 claimed they were, but
  nothing ever registered them) — marked beta while Mochi is the
  animation testbed; ``package_skill`` + ``benchmark_skill`` marked
  beta while the 0.5.x skill-tree / marketplace work is in flight
  (the proven playbook tools — ``skill``, ``reload_skills``,
  ``list_skill_dir`` — stay un-gated). 4 regression tests.

**Known-not-fixed (flagged, needs operator decision):**
- Voice latency metrics stamp t0 at orchestrator receive
  (`main.py:2298`) — STT + bus-hop time invisible; `LatencyReport`
  TTFT fields hardcoded 0.0. Belongs to the voice-pipeline review.
- Tool-layer singletons (`vision.py`, `listen.py`, `browser.py` model
  caches / session; `skill_registry/toolsets.py` `_active` visibility
  set) are module-global — concurrent multi-instance dispatch races.
- `HermesXMLAdapter` / `MLXAdapter` are exported + tested but never
  constructed in production; HermesXML with an in-process runner would
  reintroduce the zombie-decode-on-stale class (no abort machinery).
- 7 pre-existing `test_lilith_face.py` failures on the branch tip
  (Mochi-style face rewrite changed the backdrop the test asserts) —
  animation scope.

---

## Findings & fixes — 2026-05-22 runtime sweep

**Fixed:**
- **Permission flow** — `core/permissions.py` (process-global policy fallback so worker threads resolve it) + `interfaces/tui/app.py` (`_TuiConfirmationProvider` rewritten to hermes's Event pattern: the worker posts a request and blocks on a `threading.Event`; the REPL routes the user's next typed line back as the answer). This is *the* bug behind every "confirmation refused" the user hit.
- **`_shakedown.py`** — the runtime harness was itself out of date: it installed no permission policy (so `write_file` and every tier-gated path hit `DenyAllProvider`), carried stale tool-name expectations, and aborted at exit. Now installs an allow-all policy, expectations corrected, and `os._exit`s cleanly.

**Noted — not JROS bugs:**
- **F1 — ggml-metal teardown abort.** The in-process llama-cpp model's Metal context aborts (`GGML_ASSERT` in `ggml_metal_device_free`) if torn down by C++ static destructors at interpreter exit — a known upstream llama.cpp issue (PR #17869). The shakedown now `os._exit`s past it; the long-lived TUI frees the client in `JaegerTUI._shutdown` while the interpreter is alive. **If the TUI is ever seen to exit with code 134, apply the same `os._exit(0)`-after-cleanup mitigation in `main.main()`.**
- **F2 — model routing.** The shakedown's local Gemma-4 prefers `execute_code` over the dedicated `get_time` / `calculate` tools and declined `schedule_prompt`. Model behaviour / prompt-tuning, not a broken pipeline — the tools themselves work.

**Cross-thread bug class — contained.** The permission and mid-tool-interrupt bugs were the same class: the concurrent-TUI rebuild moved turns to a worker thread, and state set on the main thread didn't cross. A sweep for `ContextVar` / `threading.local` found **`permissions._current_policy` was the only `ContextVar` in the codebase** — now fixed with a process-global fallback. `_delegate_depth` is intentionally per-thread. No other landmines of this class remain.

---

## Open work (feature-level, tracked in the audits)

- Main-loop R4–R8 rebuild — internals **A1** (context compression) + **A10** (memory pipeline) + tool/skill **#5** (result formatter) + **#11** (result budget).
- tool/skill **#7** (MCP OAuth), **#10** (tool registry).
- **Daemon split — DROPPED 2026-06-14.** JROS converged on fused mode (one process, TUI in foreground). The daemon scaffold (server/client/protocol/lifecycle/attach/event_bus/chat_ops) was removed; its in-process CLI verbs moved to `jaeger_os/cli/verbs/`. Forward direction is the windowed app + tray (see `jaeger.toml`); the `rich_tui` window surface is parked in tree for that rework. Archived brief: `docs/archive/JROS_DAEMON_ARCH_BRIEF.md`.
- **Tool guardrail controller** (review finding #4 — deferred). Loop-backstop still catches the worst case.
- **Parallel tool execution** (review finding #5 — deferred). Read-only / path-disjoint batches.
- **L2 / L3 / L4 bench coverage** with the corrected umbrella-aware scorer. L1 is baselined; deeper levels need a re-run after the scorer's `_UMBRELLA_EQUIVALENTS` map is applied to L2/L3/L4 modules.

---

## 0.1.0 ship-state — what landed this cycle

**Tests:** 997 passing. (Was ~533 at the prior STATUS snapshot.)

**Major adds:**
- **Daemon scaffold + macOS tray** (`jaeger_os/daemon/`, `jaeger_os/interfaces/tray/`). Lifecycle CLI: `jaeger start | stop | status | restart`. Phase 1.6 tray icon talks to the daemon via the same socket. **Agent still lives in the TUI process.** — **Removed 2026-06-14:** the daemon arch was dropped; `jaeger_os/daemon/` is gone, its in-process verbs moved to `jaeger_os/cli/verbs/`, and the tray is parked for the windowed-app rework.
- **Pre-flight context guardrail** (`src/jaeger_os/agent/util/context_guard.py`). Prevents the "Requested tokens exceed context window" hard fail by trimming history before the call; raises typed `ContextOverflow` when even max trim won't fit. Per-tool-result truncator caps oversized payloads. Group-aware trim preserves tool-call/result pairs.
- **Lean tool surface** (`describe_tool`, catalog injection in system prompt) — **opt-in via `JAEGER_TOOLSET_SCOPING=1`**, default OFF per the 0.1.0 bench data. Infrastructure ready, default revert documented in `docs/lean_surface.md`.
- **Kanban grid view** for `/board` — Rich `Columns` + `Panel`, 5-column layout. Replaces the prior vertical list.
- **`remote_terminal` SSH tool** — Tier-4 wrapper around `ssh user@host -- <cmd>` with `BatchMode=yes` + `ConnectTimeout=10` pinned. Inbound covered by plain sshd + tmux (see `docs/remote_access.md`).

**Bug fixes from the 2026-05-24 code review** (see `docs/code_review_2026_05_24.md`):
- `reset_read_tracker()` called at the top of every `run_turn` (was leaking across turns).
- `AgentInterrupted` now sets `last_halt_reason="interrupted"` at both interrupt sites (was empty assistant message with no halt_reason).
- Tool-name normalization runs at the loop boundary against the registered set (was raw drift names landing in dispatch).
- Skip-final short-circuit suppressed when the user prompt has multi-step intent (was prematurely ending chained tasks).
- Permission / safety errors now tag `error_type` + `retryable` + (optional) `required_tier` (was generic stringified exception).
- Three Laws block wraps every system prompt via `with_three_laws()`.
- Tool-time and loop-time captured in `LatencyReport` (was both 0.0).

**TUI status-bar fixes:**
- Loaded ctx (from `client.loaded_ctx`) shown instead of just config ctx.
- `/runtime` surfaces "model trained for up to N tokens — bump config.model.ctx" when loaded < native.
- 0%-gauge bug fixed: estimator now walks both the Phase-9 dict message shape AND the legacy pydantic-ai `msg.parts[].content`.

**Drift parser:**
- Loose `<function=…>` form (Qwen3-Coder emits this without the `<tool_call>` wrapper) is now salvaged. Was leaking tool-call XML into chat text.

**Bench infrastructure:**
- `benchmark/run_model_sweep.py` drives multi-model comparisons; YAML-aware config-swap; multi-level row parser.
- Scorer in `level1_routing.py` accepts umbrella forms (`memory` for the five fine-grained memory verbs, `execute_code` for `run_python`).
- L1 baseline in `benchmark/levels/history/BENCHMARK_v0.1.0_baseline.md`.

**Model recommendation (from `BENCHMARK_v0.1.0_baseline.md`):**

| Use case | Model |
|---|---|
| **Default / voice-interactive** | gemma-4-E4B-it-Q4_K_M (97.1% routing, 1.6s p50, 5.3 GB) |
| Conservative default | gemma-4-26B-A4B-it-Q4_K_M (97.1%, 3.0s p50, 15.7 GB) — current JROS default |
| Deep Think coder | Qwen3-Coder-30B-A3B (94.1%, 3.2s p50, 18.6 GB) — already the configured coder |
| Smallest viable | gemma-4-E2B-it-Q4_K_M (94.1%, 1.2s p50, 3.4 GB) |
