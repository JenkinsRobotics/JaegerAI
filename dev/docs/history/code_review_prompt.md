# Code-review prompt for Fable 5 — JROS agentic pipeline (skills / tools / memory / bench)

You are a senior engineer doing a rigorous quality review of recent work on **JROS**
(Jaeger OS), a local-first agentic assistant framework. Read the actual code — don't
review from this summary alone; it's orientation, not ground truth. The repo is a git
checkout on branch `0.6.0`; the work under review is roughly the last ~25 commits
(from `f189f76` to `HEAD`). `git log --oneline -30` and diff freely.

## What JROS is
An agent that runs on SMALL LOCAL models (gemma-4 **E4B** ~4B and **26B-A4B-QAT**),
not a frontier API. Everything is shaped by that constraint: routing accuracy degrades
as the visible tool surface grows, a 4B fumbles anything it has no cheat-sheet for, and
prompt wording matters. The loop is: **research → plan → execute → verify → reflect**.
There is a benchmark (`dev/benchmark/bench.py`, 81-case corpus in
`jaeger_os/core/bench/cases.py`, plus a parallel corpus `cases_b.py`) that gates changes.

## Core philosophies to review AGAINST (flag anything that violates these)
1. **Skills are cheat sheets.** A skill (`jaeger_os/agent/skills/*/SKILL.md`) hands the
   small model the exact knowledge + EXACT registered tool names + a tight SOP. The #1
   bug is a skill documenting a tool name that isn't actually registered → the model
   hallucinates that call. Tool names must be verified against the real registry (from a
   FULL agent boot, not a bare import — build-time tools like `delegate_task`/`clarify`
   register in `main.py`). See `dev/docs/reality/skill_standard.md` (the 8-point standard).
2. **Individual named tools beat action-dispatch umbrellas for a 4B.** Measured: one
   `kanban(action=…)` umbrella hurt routing vs five `board_add/view/move/update/delete`
   verbs; knowledge that would bloat an umbrella's `action` list goes in a SKILL instead.
   Umbrellas are OK only where they already route well (`memory`, `list_skills`).
3. **Never game the benchmark.** Fix genuine scorer false-negatives (a correct answer
   marked wrong), never loosen a case to pass. Harden the agent, not the test.
4. **Memory: SQL for long-term, JSON for short-term** (`dev/docs/reality/memory_architecture.md`).
   Long-term facts are subject-attributed, provenance-tagged, and traceable over time.
5. **Correctness over cleverness; delete dead code; no pre-1.0 back-compat shims.**
6. **Bench-gate every behavior change; verify claims against real output, never fabricate.**

## What changed this session (the review surface)
- **Skill framework** — all ~94 skills brought to the 8-point standard: correct/real tool
  names, boundary descriptions, `requires_tools` + `related_skills` frontmatter. New
  skills: `skill-builder`, `deep-think`, `self-improvement`, `memory-keeping`, `kanban`.
  A regression was caught + fixed: subagents were given a tool list from a bare import
  (missing `delegate_task`) and wrongly stripped it from 8 skills — restored.
- **Tools** — `board_*` individual verbs + a `kanban` skill (umbrella dropped);
  `skill`→`list_skills`, `load_toolset`→`load_tools` (symmetric surface); sharpened
  `propose_deep_think_task` description; new `reflect` tool (2nd-person after-action
  journaling to `reflections.md`).
- **Memory redesign** (`jaeger_os/core/memory/sqlite_store.py`, `memory.py`,
  `agent/tools/memory.py`) — schema v2: `facts(subject, key, value, category, source,
  tags, note, …)`, PK `(subject, key, source)`; new append-only `fact_log` (history);
  idempotent v1→v2 rebuild migration; `remember/recall/recall_history/forget` are
  subject-scoped + source-filtered (operator's recall ignores `benchmark` facts). Removed
  dead `facts.py`.
- **Bench harness** — fixed false-negatives (thousands-separator, phrasing); the hermetic
  snapshot now covers `state.db`/`sessions.db` (+WAL) — it previously leaked bench writes
  into the live SQL permanently; bench writes are tagged `source='benchmark'`; added
  **Benchmark B** (`cases_b.py`, `--corpus B`) — same categories, new prompts, to catch
  prompt-overfitting.
- **Gemma dialect** (`jaeger_os/agent/dialects/gemma.py`) — tolerant tool-call parser that
  salvages calls when the model drops the closing token.

## Your review — go deep on these, ranked by risk
1. **Memory correctness (highest scrutiny):** the v1→v2 migration in `sqlite_store.py`
   (`_migrate_facts_table` + `_ensure_schema`) — is the rebuild safe, idempotent, and
   ordered before the indexes that reference new columns? WAL handling? The composite PK
   + `INSERT OR REPLACE` + the source filter in `memory.py` — any way a user fact gets
   clobbered or a benchmark fact leaks into operator recall? Concurrency (the writer lock)?
2. **Tool/skill integrity:** does every tool a SKILL.md tells the agent to call actually
   exist in the registry? Any phantom tool names left? Are the new tools (`reflect`,
   `board_delete`, `list_skills`) classified in exactly one toolset (the classification
   test)? The name-collision where a tool function shadows its own submodule (`reflect`,
   `memory`) — real problem or harmless?
3. **Bench harness reliability:** is the hermetic isolation now actually complete? Could
   anything still pollute the operator's live instance? Are the Benchmark-B expected
   values internally consistent (esp. multi-case shared-state like the memory cases)?
4. **Architecture soundness:** the SQL-vs-JSON split, the individual-tools-vs-umbrella
   stance, the reflect/verify pipeline — coherent and consistent across the code? Any
   place that contradicts the stated philosophy?
5. **Dead code & consistency:** leftover legacy (the `facts.json` importer still in
   `memory.py`?), stale docstrings/examples, inconsistent naming.
6. **Test coverage:** are the risky new paths (migration, source isolation, history,
   individual board tools) actually covered? What's untested that should be?

## Output
Return findings **ranked by severity** (correctness/data-loss first, then reliability,
then quality/consistency). For each: file:line, the concrete failure scenario, and a fix.
Call out what's genuinely good too (so we keep it). End with a short verdict: does this
work uphold the six core philosophies, and the top 3 things to fix before it's trusted.
Be adversarial about the memory migration and the "no phantom tool names" claim — those
are where a regression would hurt most.
