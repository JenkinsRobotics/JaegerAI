# JROS — future backlog (things to look at, not yet built)

Living list of deferred work. Each item says WHY it's deferred and roughly what
it needs. Nothing here is scheduled; it's the "later" pile.

## Bench-failure taxonomy (2026-07-03) — WHY the current cases fail
From reading the actual agent output on every failing case (E4B 77/81, 26B 75/81).
There are NO clean scorer false-negatives left this round (the "9,999" and
"does not exist" ones were fixed). The remaining failures fall into 5 kinds:

1. **PLAN-narration halt (fixable, NOT a capability gap) — the #1 lever.**
   `rec_python_syntax`, `rec_python_zerodiv` (E4B). The prompt asks for the
   nonexistent `run_python`; the agent CORRECTLY recognizes it and writes
   `PLAN: execute_code(...)` — then STOPS at iteration 1 without calling it. It
   knew the answer; the runner let it halt after the plan line. Same root cause as
   `skill_native_tier` under scoping. → **The planning lever** (make an emitted
   `PLAN:` line obligate its tool call in the same turn) flips all of these.

2. **Strong model did the task WITHOUT the expected tool (borderline).**
   `help_overview`, `skill_codebase_inspect` (26B). The model answers the overview
   / does the codebase inspection directly instead of calling `help_me` /
   `use_skill`. This is capability, not weakness — the scorer wants the tool.
   Leave un-gamed; optionally relax those two cases to accept the direct answer.

3. **Multiturn chain fragility (brittle test design).**
   `chain_weather_t3` (26B, needs "Tokyo" but round-1 saved city-less weather),
   `mt_file_round_2` (E4B, round-2 read fails because round-1's file isn't there).
   The failure is upstream in the chain, not the graded turn. → Harden the
   multiturn fixtures so round-1 reliably persists the required content.

4. **Real behavior gap.** `wf_triage_defer` (26B): computes B correctly but only
   SAYS it "noted" A/C — never actually `board_add`s them. Triage discipline.

5. **Environment (unpassable headless).** `pf_macos_do` (both), `skill_native_tier`
   (26B): GUI driving with no display → repeats identical clicks → loop-halt.
   → A scorer that credits "loaded the right skill + attempted the right tool."

Highest-value fix: **item 1 (the planning lever)** — flips 2-3 cases across models
and is the same lever behind the scoped-path losses.

## The closed-loop agentic pipeline (ongoing, multi-day continuous-improvement zone)
Target loop: **research → plan → execute → verify → reflect**. We've been tuning
the first half (SKILLS-FIRST triage, tool routing). The back half is where the
learning lives and it's underbuilt. Build it CAREFULLY, in order:

- **VERIFY (small, high-value, do soon):** a runner/prompt gate that catches the
  #1 failure — the agent emits a `PLAN:` line but ZERO tool calls and the loop
  ends. On end-of-turn with a plan-but-no-call, nudge once ("you planned but
  didn't act; do it now") instead of accepting it as final. Flips `rec_python_*`
  and scoped `native_tier`. (The old deny-and-retry gate regressed 73→66 — nudge,
  don't deny.)
- **REFLECT (STARTED today — journaling only):** added the `reflect` tool +
  framework REFLECT bullet. After a non-trivial task the agent records
  what-worked / what-was-hard / the-one-lesson to `<instance>/memory/reflections.md`.
  Today it ONLY journals — building the practice. NOTHING auto-creates skills yet.
- **REFLECT → skills (the eventual feature, careful setup):**
  1. *Make new skills* — a successful, novel, repeatable multi-step trajectory
     becomes a skill (reflection decides + `propose_deep_think_task` with the
     captured trajectory as the spec; Deep Think authors it).
  2. *Prune + refine skills* — the existing sweep (`skill_review.py`) already
     scores skills from `skill_note` telemetry and proposes Deep Think reviews for
     strugglers; `curator`/`retire` archive stale ones. Wire reflection into this
     so live task-failures also feed it.
  This must be staged: journal (now) → nudge the loop (verify+reflect prompt/
  runner hardening) → reflection triggers skill creation → creation feeds prune/
  refine. Each stage benched before the next.

Note: `skill_note` (per-skill-use telemetry → the Deep Think review sweep) and
`reflect_on_task` (fires after a background Deep Think task → reflections.jsonl +
memory) ALREADY exist. The gap is task-level reflection on LIVE turns and the
reflect→new-skill step.

## Session persistence (operator-requested future look)
Hermes has `hermes_state.py` — SQLite + FTS transcript persistence with
parent-session chains, so a restart doesn't lose the conversation. JROS
deliberately has NOT adopted it: it's daemon/state architecture and needs a plan
+ operator approval first ([[feedback-daemon-arch-needs-plan-and-approval]]).
Today JROS seeds a fresh session with a bounded `[PREVIOUS SESSION — REFERENCE
ONLY]` digest (orientation, not replay). Full-fidelity persistence is the gap.
When picked up: design pass first (schema, retention, the clean-slate-vs-resume
boundary), then approval, then build.

## Import candidates from Hermes (breadth JROS lacks)
Hermes has 171 skills (JROS 93) — ~88 niche optional-skills + more integrations.
Worth importing, held to the JROS 8-point skill standard on the way in:

- **Integrations → `jaeger_os/plugins/`** (JROS already has discord/telegram/
  imessage/mcp + a plugin registry): **HomeAssistant** (`homeassistant_tool.py` —
  not in JROS, operator wants it), richer **Discord** (JROS has a basic plugin).
- **AI generation** (operator wants): Hermes `image_generation_tool.py` +
  `fal_common.py` (fal.ai) — JROS has `image_generate`; could add more backends
  (fal, replicate) as a media plugin/skill.
- **Selectively from the 88 optional-skills** IF they fit JROS's use case — skip
  the deep-niche finance/bio/crypto ones unless wanted.

## Other deferred levers (from prior sessions)
- **Two-pass persona voice filter** — restore character voice over the vanilla
  worker output (persona is currently OFF in execution).
- **Scoped surface as default** — validated (`JAEGER_TOOLSET_SCOPING`), still opt-in.
- **26B on the current stack** — benched at 75/81; keep re-checking as changes land.

## 0.7 goals
- **InfluxDB for robot/hardware telemetry** — JP01 `/sense/node_health` (1 Hz),
  motor positions, latencies. Time-series firehose; wrong fit for SQL. Keep it
  SEPARATE from the SQL knowledge memory. (Operator call, 2026-07-03.)
- Remove the one-shot `facts.json`→SQL importer in `memory.py` once no
  un-migrated instance can exist (facts.py itself already removed).

## Scenario test suite (deferred — implement later)
- dev/docs/reality/scenario_test_suite.md — 25 operator-authored full-system real-world prompts (day-to-day + advanced), sorted scriptable/watch/security. NOT built; security gates are the priority slice when picked up.
