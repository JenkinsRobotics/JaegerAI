# Pipeline: Skill Self-Improvement

**What it is:** how a skill gets better over time *safely* — a new version is
proposed, gated, scored, and only kept if it beats the prior one; otherwise it
rolls back. Verified in code; this is a map, cite the source before changing.

## The safety loop (per skill)

```
propose/rewrite a skill version
        │
   SMOKE GATE   ── tests/smoke_test.py  (pass/fail)
        │            run by the loader (skill_registry/skill_loader.py);
        │            a skill that FAILS smoke is *skipped*, not registered
        ▼
   SCORED EVAL  ── tests/benchmark.py  (prints {"score":0-1,"passed","total"})
        │            run by skill_benchmark.benchmark_skill(layout, name)
        ▼
   COMPARE      ── delta = score − previous_score
        │            previous from benchmark_history.jsonl (_previous_score)
        ▼
   KEEP BETTER / ROLL BACK   ── curator.py (assess, rollback, retire)
```

## Layout a skill carries
```
skills/<skill>/
    SKILL.md
    tests/
        smoke_test.py           ← pass/fail gate (loader runs it)
        benchmark.py            ← scored evaluation (skill_benchmark runs it)
    benchmark_history.jsonl     ← appended every run (score history)
```

## Key files / functions
- `skill_registry/skill_benchmark.py`
  - `benchmark_skill(layout, skill_name)` → runs `tests/benchmark.py`, records to
    history, returns `{ok, skill, score, passed, total, delta, previous_score}`.
  - `_previous_score(history)` → most recent prior score (for the delta / keep-better
    decision).
  - `_append_history(...)` → appends each run to `benchmark_history.jsonl`.
- `skill_registry/skill_loader.py` — runs each skill's `smoke_test.py`; a failing
  skill is skipped (never registered), so a broken self-edit can't reach the agent.
- `skill_registry/curator.py` — `assess` (score/staleness/usage), **rollback**
  ("move an archived skill back where it came from"), retire.
- `skill_registry/capability_state.py` — `SkillState` (per-skill state tracking).

## Guarantees this gives
- A self-edit that **breaks** → fails smoke → **never loads** (agent unaffected).
- A self-edit that **loads but is worse** → lower benchmark score → **not kept**.
- A regression → **rollback** restores the prior version.

## Relation to the discovery pipeline
This is the "reflect/improve" arm of the task loop. Its planned mirror — *gap →
propose a NEW skill* and *staleness → retire* — is tracked as **P4/P7** in
`dev/docs/agentic_skill_pipeline_backlog.md`. The broader idea (a locked
**regression bench** re-run after each self-improvement so agreed routing/order
can't silently drift) is the reliability practice noted there.
