# JROS agentic runners — the two-tier design (locked 2026-07-04)

JROS deliberately runs **two different agentic architectures**, one per tier,
so each performs best at its own function:

| | **Standard runner** (realtime loop) | **Deep Think runner** (background pipeline) |
|---|---|---|
| Used for | every live turn (chat, voice, bench) | big queued tasks (skill builds, long fixes) |
| Latency budget | seconds — voice-first | none — runs unattended |
| Architecture | **soft loop, hard boundary** | **assembly line** (Method B, where it pays) |
| Who owns control flow | the model (fluid), runner guards the EXIT | the runner (staged), model executes stages |
| Context | one continuous context, compacted | dedicated clean context per task/stage |
| Verification | observable checks at the exit door + ONE nudge | observable evidence before `mark_done` + replan |

The split exists because we MEASURED both extremes failing:
- **Hard control in the live loop fails:** the deny-and-retry planning gate
  regressed E4B 73→66 (reverted). A 4B improvises well mid-flow; blocking it
  mid-flow breaks flows it was already handling.
- **Pure soft prompting fails at the finish line:** the loop's exit door is
  `if no tool calls: turn done`, so a model that narrates a `PLAN:` instead of
  acting, or *claims* "I've noted it" without calling the tool, exits early.
  Observed as `rec_python_syntax`/`rec_python_zerodiv`, corpus-B
  `write_bench_txt`, scoped `skill_native_tier`, 26B `wf_triage_defer`.

Design rule for both tiers: **verify with observable evidence (tool results,
DB traces), never with model declarations.** A model can say "SUCCESS"; a tool
result can't lie.

---

## Runner 1 — the standard realtime loop: "soft loop, hard boundary"

Three stations, one model context, zero added latency on the happy path:

```
            STATION 1                      STATION 2                 STATION 3
   ┌──────────────────────────┐    ┌─────────────────────┐    ┌──────────────────┐
   │  THE FLUID LOOP          │    │  VERIFY GATE        │    │  PERSONA PASS    │
   │  research/plan ⇄ execute │───▶│  runner-owned,      │───▶│  one bounded     │──▶ user
   │  (one context, pivots    │    │  observable checks, │    │  call: restyle   │
   │   allowed — UNCHANGED)   │    │  ONE nudge max      │    │  the answer only │
   └──────────────────────────┘    └─────────────────────┘    └──────────────────┘
              ▲                            │                          └─ reflect (post-turn tool)
              └────── nudge re-enters ─────┘
```

### Station 1 — the fluid loop (do not touch)
The interior stays exactly as benched (E4B 77-78/81 band): the model moves
freely between researching, planning, and executing, pivots on tool errors,
and is never denied mid-flow. All existing recovery machinery (warn-before-
halt, result-hash no-progress, post-tool empty-response nudge, wind-down
grace) is unchanged.

### Station 2 — the verify gate (the reliability fix)
Lives at the loop's ONE exit door in `jaeger_agent.py` (the
`if not tool_calls:` branch). Runs only on a candidate FINAL answer; costs
nothing when the answer is clean.

- **Check A — plan-halt:** the candidate text is a plan, not an answer
  (a line starting `PLAN:`). The model "ran out of steam" after narrating.
  → inject ONE synthetic nudge: *proceed now, emit the tool call*.
- **Check B — claim-vs-action:** the text claims a completed mutation in the
  first person ("I've saved/added/noted/remembered/scheduled/queued…") but no
  matching successful tool call ran this turn (the runner tracks per-turn
  tool successes for free). → ONE nudge: *call the tool now, or say plainly
  it was not done*.
- **Check C — clean:** pass through untouched.

Soft-gate guarantees (the lessons from the 73→66 failure):
- max ONE verify nudge per turn; the nudge is synthetic and does NOT persist
  in session history (same mechanism as the existing post-tool nudge);
- the gate NEVER denies: if the model still doesn't act after the nudge, its
  answer is accepted — a failed nudge is information, not a wall;
- claim-verb lists stay tight (first-person + mutation verbs mapped to tool
  families) so "I've analyzed the options" can never false-trigger;
- kill switch: `JAEGER_VERIFY_GATE=0`.

### Station 3 — the persona pass (voice without pollution)
Workers run vanilla (measured: persona in the execution context costs the 4B
~7 points). After the gate passes, ONE bounded clean-context call restyles
the final answer in the character's voice: context = final text + character
fragment only (no tools, no history). The prompt pins **"preserve every
fact, number, and file path verbatim."**
- Skips: deterministic skip-final tool answers, halt/empty outputs.
- The bench measures the ENGINE persona-off; the filter is measured
  separately (persona cases + latency delta). Config-flagged.
- The one prompt exception is the NAME (`identity_name` fragment: one line,
  ALWAYS identity.yaml's `name` — a wrong name can't be fixed downstream
  because the filter preserves facts verbatim). Identity vs character
  standardization (operator decision, 2026-07-05): the character NEVER
  supplies the agent's name — it's the persona only ("a robot like Jarvis,
  but I will name him Ted"); the filter context injects "your name is
  <identity.name>; you embody <character>'s persona" so the rewrite keeps
  the instance name. `JAEGER_BENCH_NEUTRAL_IDENTITY` is now a NO-OP (the
  bench runner still sets it, harmlessly): it used to force exactly this
  identity.yaml-only prompt, which is the behaviour everywhere now.
  Measured why the character name had to leave the worker prompt: with
  HAL 9000 active, free_text_story ("a story about a robot")
  deterministically wrote its story about HAL 9000 (2/2 vs 0/2 A/B on E4B,
  2026-07-05) — a character name in the worker prompt tints free text and
  false-negatives answer_contains.

### Station 4 — reflect (already shipped)
The 2nd-person `reflect` tool journals after non-trivial tasks
(reflections.md). Future: reflection feeds skill creation (backlog).

### Bench criteria for the gate
Corpus A both models + corpus B on E4B (B is the sensitive instrument for
the plan-halt class). KEEP iff corpus A ≥ baseline (E4B 77, 26B 75) AND
corpus B improves. REVERT on any regression — the 73→66 gate taught us the
shape of this failure.

---

## Runner 2 — the Deep Think assembly line (background tier)

Deep Think already has the pipeline's SHELL: approval gate → dedicated
clean context + coder-model swap → (run) → reflect. What it lacks is the
pipeline's VALUE — enforcement:

**Today (main.py daemon loop):** `run_command(...)` then
`queue.mark_done(task.id, "completed by daemon")` — **unconditional**. If the
call returns, the task is "completed", even if the model answered "I couldn't
do this". Only a raised exception marks failure. The measured
verify-and-keep-only-if-better story lives in the PROMPT; the runner never
checks any of it.

### Phase 1 — verify-before-done (build after the gate ships)
Replace trust-by-return with observable evidence:
1. **Tool-trace check:** query the `tool_calls` SQL table for the task's
   session (`daemon_<task_id>`) — did any successful mutating call happen
   (write_file / append_file / patch / reload_skills / record_skill_revision)?
   A skill-development task that wrote nothing did not complete.
2. **Failure-signature check** on the final text ("I was unable", "cannot
   complete", "gave up").
3. Pass → `mark_done`. Fail → **one bounded replan cycle**: re-queue ONCE
   with the failure evidence appended to the description (tagged so a second
   failure goes to `mark_failed` with the reason, never loops). Reflect
   captures the outcome either way (already wired).

### Phase 2 — the full staged pipeline (backlog)
plan checkpoint (plan saved as an artifact) → execute → per-task-type
programmatic verify (skill tasks: smoke passes + `benchmark_skill` delta ≥ 0
+ revision logged) → replan loop. True Method-B, justified ONLY here:
latency-free, unattended, huge contexts, objective success criteria.

### Explicitly rejected (both tiers)
- Hard phase gates / context wipes inside the LIVE loop (measured 73→66).
- Multiple model calls per live turn (voice latency; most turns are 1-2 tools).
- Model-declared SUCCESS/FAIL strings as control flow (declarations can lie;
  tool results and DB traces can't).

---

## Inference lanes — two KV contexts on one loaded model

Both runners share ONE loaded model but need TWO isolated KV caches. Why:
llama-cpp-python's `Llama` owns a single `llama_context` with a single-slot
prefix cache — the worker lane keeps a ~20K-token conversation prefix warm,
but any clean-context side call on the same context EVICTS it, and the next
turn pays a full re-prefill. Measured 2026-07-05: the persona filter (station
3) drove **ttft 41–44s with the filter ON vs 0.3–0.4s OFF** — the filter's
own call is cheap (~1–3s); the eviction was the whole cost.

**Fix (`core/models/aux_lane.py`): a second `llama_context` on the SAME
`llama_model`.** llama.cpp separates weights (`llama_model`, shared) from
KV+compute (`llama_context`, cheap); `spawn_aux_context` builds a full
`Llama` whose model-load step ADOPTS the worker's already-loaded weights
(scoped constructor patch + a no-op-close proxy so neither instance can free
the shared model out from under the other). Cost: **+0.13 GB** (KV/compute
buffers only, no second weight load), 0.08s to spawn.

- **Worker lane** = the agent loop (`LocalLlamaAdapter` → `client.llm`).
  Big context (`model.ctx`, default 32K, ≤131K = gemma-4's train ceiling);
  its warm prefix is now never evicted by anything.
- **Aux lane** = every side-channel model call, through the ONE chokepoint
  `LlamaCppPythonClient.chat()`: the persona output filter, the skip-final
  finalizer, reflection, deep-think planner/digests, memory review, goal
  clarify/eval. Small context (`model.aux_ctx`, default 4096). Lazy-spawned,
  `_aux_lock` serialises aux-vs-aux, **fail-open** to the old shared-context
  path (spawn failure latches; `aux_ctx: 0` disables the lane entirely).

Result — persona voice AND pre-persona speed:

| turn 2 (warm), persona ON | before | after |
|---|---|---|
| wall clock | 48.8s | **5.2s** |
| ttft | 45.6s | **0.71s** |

Rejected alternative: `save_state()/load_state()` around each aux call —
0.32s+0.37s memcpy at 6K tokens, scales linearly (~2s+/0.5GB at 20K), and
the aux call still cold-prefills in the borrowed context every time. Dual
context wins on every axis. Config: `model.ctx` + `model.aux_ctx` (both
over the bridge config query / `save_config`; apply on restart — KV is
allocated at model load).

**Design rule this establishes:** any NEW side-channel model call routes
through the aux lane (`client.chat()`), never the worker context — or it
regresses this. The worker context is sacred; the aux context is disposable.

---

## Status
- Station 1: ✅ shipped (record band).
- Station 2 (verify gate): ✅ SHIPPED + benched 2026-07-04 — corpus A: E4B
  78/81 (ties the record), 26B 76/81 (new 26B high); corpus B 73/81
  (improved). Target class fixed (rec_python_*, write_bench_txt, pf_arxiv
  false-positive caught by A/B and fixed with the plan-requested stand-down).
- Station 3 (persona pass): ✅ SHIPPED 2026-07-04 — one bounded clean-
  context call at the user boundary; fail-open; live-verified (0.5-1.3s,
  facts/paths preserved verbatim). Bench isolated by construction.
- Station 4 (reflect): ✅ shipped (journaling).
- Inference lanes (aux context): ✅ SHIPPED 2026-07-05 — persona ON warm
  ttft 45.6s → 0.71s; bench held 79/81 (nothing leaked between lanes).
- Deep Think Phase 1 (verify-before-done): ✅ SHIPPED 2026-07-04 —
  completion decided by the tool_calls evidence trace + failure-admission
  scan; one informed pre-approved replan cycle, then failed. mark_done is
  no longer trust-by-return.
- Deep Think Phase 2: backlog.

## Where the pipeline stands (2026-07-05)
E4B **79/81** (all-time high) · 26B 75-76 · corpus B 73 · warm ttft ~0.7s
with full persona. The realtime runner (fluid loop + verify gate + aux-lane
persona filter + reflect) and the Deep Think staged runner are both live and
measured. The engine work is essentially complete for this line; remaining
levers are backlog (Deep Think Phase 2, reflect→skills, the PLAN-halt tail).
