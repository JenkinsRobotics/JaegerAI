# Skill self-improvement — notes-journal + Deep Think loop (PLAN)

**Status:** base loop (phases 1–4) **SHIPPED in 0.6**, on by default — notes
journal, threshold trigger, measured Deep Think rewrite (smoke + `benchmark_skill`,
keep-if-better/revert), revision log, `jaeger skills notes` / `revisions`. The
**Refinement** section at the bottom (second-person audit · richer post-use
summaries · probabilistic severity-weighted trigger · new-skill spawning ·
per-skill archive · scoring/retirement) is the agreed next design from the
2026-06-27 brainstorm. **§1–§7 all SHIPPED (Plan A: structured summary +
probabilistic trigger · Plan B: second-person review + prompt-level validation/
spawn · Plan C: per-skill archive + scoring/retirement).** The core data +
lifecycle modules now live under **`jaeger_os/core/skill_improvement/`**
(`skill_notes` · `skill_revisions` · `skill_maintenance`), grouped to match the
codebase convention; the trigger + review stay in `agent/background/skill_review.py`.

## The idea

JROS already has the *machinery* for skill self-improvement (versioned instance
skills, a smoke-test gate, `benchmark_skill` with per-version deltas, the Deep
Think background runner, the skill tree) — but no *loop* that drives it. Hermes
has the loop but does it crudely: every N tool-iterations it forks the live
agent and re-reads the raw turn transcript, then rewrites skills with no
approval, mid-conversation.

We adopt the loop but in a JROS-native, **measured** form:

```
FOREGROUND  (live turns, e4b, voice)
  use a skill  →  agent jots a short post-use note (smooth/slow/issues/failed)
                  → appends to <instance>/memory/skill_notes.jsonl   (cheap, no model)
  notes pile up / a skill keeps misbehaving
                  → agent calls propose_deep_think_task("improve skill X — see its notes")

DEEP THINK / DEEP-SLEEP  (idle or asleep, 26b-a4b-qat — the strong model)
  runner picks up the task when the machine is free
  → reads skill X's accumulated notes → rewrites the recipe (new _vN)
  → RE-MEASURE vs the prior version:
        smoke test       (correctness gate — already in the loader)
        benchmark_skill  (improvement delta — already records to benchmark_history.jsonl)
        next real uses   (does it hold up live? fresh notes)
  → better → keep (new version wins)   |   worse → revert (free; append-only)
  → note the outcome → loop
  apply-vs-propose is governed by the AUTONOMY MODE:
        auto        → auto-approve the task + apply on a passing gate
        scoped/ask  → leave it proposed in the board for operator approval
```

## Why this shape

- **No live impact.** The heavy rewrite runs idle/asleep, never mid voice-turn
  (Hermes forks mid-turn). Foreground stays e4b/fast; the rewrite uses the
  strong deep-think model.
- **Sees cross-use patterns.** Hermes reviews one turn at a time; accumulated
  notes catch "this skill failed the *same way* 3 times" — the best fix signal.
- **Measured, not trusted.** A rewrite only sticks if it passes smoke AND shows
  a positive `benchmark_skill` delta AND holds up in the next uses. This is the
  agent's own "verify, don't confabulate" rule applied to itself; regressions
  roll back for free (append-only versions).
- **Scope = recipe-skills only.** The `nodes/` subsystems and the skill *tree*
  (node-capability XP/mastery) are a separate, longer-term track — not this loop.

## Reuse (most of it already exists)

| Need | Reuse |
|---|---|
| Background work period | Deep Think runner + deep-sleep mode |
| "Agent queues work when it feels it" | `propose_deep_think_task` |
| Approve-vs-auto | board backlog→ready gate, gated by the autonomy mode |
| Write / version / smoke / reload a skill | `file_write` → `<instance>/skills/`, smoke-gate, `reload_skills` |
| "Did it actually improve?" | `benchmark_skill` (score + delta + `benchmark_history.jsonl`) |
| Strong model for the rewrite | deep-sleep already swaps to `26b-a4b-qat` |

**Genuinely new:** (1) the `skill_note` journal, (2) a prompt nudge to journal
notable uses, (3) the threshold/agent-deemed trigger → `propose_deep_think_task`,
(4) the "review notes → rewrite → re-measure → keep/revert" Deep Think task type.

## Safety rails (mostly free)

Sandboxed to `<instance>/skills/` (core is read-only) · append-only `_vN`
versions (revert = stop activating a folder) · smoke-gated (a broken rewrite
never activates) · benchmark-gated (a regression rolls back) · never touches
core/config/identity/memory-internals/credentials. One new bit: run the
guard/exfil scan **before** activating a rewrite, not after.

## Phases

1. **Notes** (this phase) — `skill_note(skill, outcome, note)` write tool +
   `skill_notes(skill="")` read tool + a per-skill journal at
   `<instance>/memory/skill_notes.jsonl` + a prompt nudge. Pure additive; just
   starts capturing signal. Nothing fires yet.
2. **Trigger** — when a skill's notes cross a threshold (count / repeated
   `failed`/`issues`) or the agent deems it, propose a Deep Think skill task.
3. **The Deep Think skill task** — read notes → rewrite `_vN` → smoke +
   `benchmark_skill` re-measure → keep-if-better / revert-if-worse → journal the
   result. Apply-vs-propose by autonomy mode.
4. **Surface** — `jaeger skills notes` / `jaeger skills reviews` so the operator
   sees what was journaled + changed.

## Open decisions (revisit at phase 2)

- ~~Exact trigger threshold~~ — **decided**: probabilistic, severity-weighted
  (see Refinement §2 below).
- Phase 2 ships default-OFF + propose-only until watched, then enable `auto`.
- In `auto`: always emit a dimmed "drafted/updated skill X (benchmark +Δ)" notice.

---

# Refinement — second-person audit + probabilistic trigger (brainstorm 2026-06-27)

The base loop above (phases 1–4) shipped. This section is the agreed next design.
Net: keep the measured backbone, upgrade four things and add three.

**Scope confirmed:** this loop is about **how the agent works** — cross-cutting
efficiency (step economy, batch/parallel, verify-don't-guess) — realized **per
skill** by improving that skill's *playbook*. Tool-skill capability rewrites
still ride the same path; the audit just feeds richer candidates.

## §1 Richer post-use summary (widens the phase-1 note) — ✅ shipped (Plan A)

After using a skill the agent writes a cheap, structured summary (no model pass
— it already has the facts):

- **objective** (verbatim, 1 line)
- **tool calls** — count + the brief ordered procedure
- **errors / retries / dead-ends**
- **issues / friction** (free text)
- **outcome** — smooth / slow / issues / failed
- optional **flag** — "review this" when it hit notable waste

Accrues per skill in the existing `<instance>/memory/skill_notes.jsonl`, widened.
Still inline + cheap; **no per-task audit pass** (Hermes' 5-call inline audit is
explicitly dropped).

## §2 Trigger — probabilistic, severity-weighted (the "neuron" model) — ✅ shipped (Plan A)

Each skill carries a running **activation** `S` = severity-weighted sum of its
post-use summaries *since the last review*:
`smooth +0 · slow +1 · issues +2 · failed +3`; an agent **flag** adds a large bump.

- **Timing:** reviews run only in **Deep Think / idle** — never mid-task.
- **Selection per idle sweep:** fire with `P = σ((S − S₀)/T)` (sigmoid, `T` =
  sharpness), with two rails:
  - **Gate:** `S < S_min` → `P = 0` (never burn a review on noise).
  - **Ceiling:** `S ≥ S_max` → `P = 1` (a bad skill can't be deferred forever by
    unlucky draws).
- Under a per-sweep budget `K`, **sample `K` skills weighted by activation**
  (importance-sample the worst first; still occasionally explore a mild one).
- Every decision **logs `S`, `P`, and the draw** → fully explainable.
- A review **consumes** `S` (resets to 0; processed summaries archived).

**Principle:** randomness is only in *scheduling* (what to look at, when). The
keep/kill decision stays deterministic + measured (§4).

## §3 The review — second-person reflection (the heart) — ✅ shipped (Plan B)

At review time (Deep Think, strong model) the agent reads the skill's accrued
post-logs and reflects **in the second person** — reviewing "your own" logged
trajectory as if it were someone else's. The grammatical distance flips it from
defending what it did to encoding what should change. Audit prompt:

1. **Objective check** — did *you* meet the verbatim objective? full/partial/no.
2. **Issues** — errors, wrong-tool, backtracks, retries (cite the summaries).
3. **Step economy** — fewer steps? which calls were redundant / serial-that-
   could-batch?
4. **Guess vs verify** — where did *you* assume instead of check?
5. **The one lesson** — a single reusable imperative ("Batch independent reads"),
   not a vibe.
6. **Skill decision** — EDIT this skill's playbook, NEW skill, or nothing.

**Honesty rule:** if step 5 can't be written as an imperative, the review
produced nothing — leave the skill untouched.

## §4 Validation — benchmark where possible, else score — ✅ shipped (Plan B prompt + Plan C scoring)

The proposed edit / new skill does **not** auto-stick:

- **Benchmarkable (tool-skill)** → the existing **keep-if-better gate**: smoke
  pass AND positive `benchmark_skill` delta, else revert.
- **Pure procedural playbook** (not benchmarkable) → **score-then-prune**: apply,
  then later reviews **grade** uses (objective met? ≤ the skill's running-median
  calls? no rework? = a win), accruing uses/wins.
- **Harden the procedural case** (closes the only soft spot vs Hermes): a fixed
  **recurring-task set** run with the lesson on vs off, tracking
  **tool-calls-per-task + first-try success**. That turns "did this efficiency
  rule actually help?" from a vibe into a number — measured, not just scored.

## §5 No-skill case → spawn a new skill — ✅ prompt-directed (Plan B)

When the lesson is worth keeping but **no skill was in play**, the review creates
a NEW playbook skill (use-when trigger + the imperative rule). **Dedup rail:**
check existing skills first; prefer an EDIT over a near-duplicate (sprawl is the
failure mode here).

## §6 History — per-skill archive — ✅ shipped (Plan C)

**Why it's load-bearing, not tidiness:** instance skills live under `.jaeger_os/`,
which is **gitignored** — so git tracks none of their evolution. The archive is
their *only* version history. It buys free rollback, the keep-if-better baseline
(§4 needs the old version to compare against), and a forensic trail for a
self-modifying agent.

Superseded playbook versions move to `<skill>/archive/` (on top of append-only
`_vN`) so the active dir stays clean and a skill's evolution is inspectable +
comparable; it pairs with the existing `skill_revisions.jsonl` (metadata: version
· origin · benchmark delta · ts). Refinements: archive the recipe + manifest
(reference, don't copy, large assets); **cap depth** (keep the last K full
versions; the revision log summarizes older ones). Revert stays free.

## §7 Pruning / retirement (new) — ✅ shipped (Plan C)

On a schedule (idle), update each skill's score and **retire** skills that never
fire or whose win-rate is poor. Curate, don't hoard — **never** auto-prune a
user-written skill.

## Maps to the phases above

- Phase-1 note → **widened** to the structured post-use summary (§1).
- Phase-2 trigger → **the probabilistic severity-weighted model** (§2).
- Phase-3 Deep Think task → gains **second-person reflection** (§3), the
  **new-skill** branch (§5), and the **score-else** validation (§4).
- Phase-4 surface → also show the activation/score + retirements.
- **New beyond the original plan:** §5 new-skill spawning, §6 archive, §7 retirement.

## Open knobs (tune at build, not now)

- `S₀ / T / S_min / S_max / K` — start conservative (high `S_min`, low `K`),
  widen once watched.
- "Win" definition for non-benchmarkable skills — starting proposal: objective
  met AND ≤ running-median calls AND no rework.
