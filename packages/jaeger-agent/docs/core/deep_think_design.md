# Sleep cycle — awake/asleep operational modes

## Vocabulary

Two orthogonal axes describe the robot's state:

* **awake / asleep** — which model is loaded and ready.
  * **Awake** = fast conversational model resident, ready for sub-second
    human turns.
  * **Asleep** = deep-think model resident, working the kanban queue without
    human interaction.
* **active / inactive** — whether the agent is currently doing work.
  * **Active** = processing a turn or kanban task.
  * **Inactive** = idle, waiting for input or the next queued task.

Examples of combined states:

| state | meaning |
|---|---|
| awake + active | mid-conversation with user, generating a turn |
| awake + inactive | awake and waiting for the next user message |
| asleep + active | processing a kanban task in deep-think mode |
| asleep + inactive | idle between queued tasks while asleep |

## Concept

The robot runs one of two modes, never both (so only one model is RAM-resident):

- **Awake mode** — fast conversational model (e.g. `gemma-4-26B-A4B-it-Q4_K_M`).
  Responsive to the user; handles conversation, routing, physical-skill
  decisions. Optimized for low Tokens/task and snappy per-turn latency.
- **Asleep mode** — accurate / specialized model (e.g.
  `Qwen3.5-9B-Q4_K_M` as the current data-validated default; specialised
  alternatives like `Qwen3-Coder-30B-A3B-Instruct-Q3_K_L` are appropriate
  when the queue is dominated by coding tasks). Works the kanban queue
  while the user doesn't need the robot. The "dreaming" state: the robot
  consolidates and builds capability.

The robot enters Asleep when the user has been gone for the **inactivity
timeout** (default **1 hour**) AND there's at least one ready kanban task.
On wake (user input), it swaps the resident model back — model load takes
**< 1 minute**, so the user sees a brief "waking up" indicator then a normal
turn. Skills/work finished asleep become immediately usable by the awake
model.

## Why this design

- **Solves the RAM constraint.** Two models co-loaded (~15GB Gemma + ~18GB
  coder) needs a 64GB machine. Mode-swap means only one is resident — works on
  a 32GB robot.
- **No quality compromise on coding.** Skill authoring escalates to a
  coding-specialized model instead of asking fast-Gemma to write integration
  code it's weak at.
- **Responsiveness is preserved.** Deep Think yields instantly on a wake
  signal; the robot is never "stuck thinking" when the user needs it.

## Locked design decisions (2026-05-19)

1. **Task source: BOTH.** The Deep Think queue is fed by (a) user-queued jobs
   ("when idle, build a Discord skill") and (b) agent-proposed jobs from gaps
   it noticed (failed tasks, missing skills, broken files). Agent-proposed
   jobs require a lightweight approval before they run.
2. **Activation: BOTH.** `/deepthink` (or a voice command) enters it on
   demand; it ALSO auto-enters after the inactivity timeout (default
   **3600s / 1 hour** since last user turn) PROVIDED the queue has at
   least one ready task. Timeout is configurable via instance config
   (`sleep_cycle.inactivity_timeout_s`).
3. **Task routing: per-task hint + sensible default.** Each kanban task
   carries an optional ``preferred_mode`` field — ``awake`` (run now in
   the realtime model, useful for "lookup current weather and decide"
   patterns), ``asleep`` (default for code/research/long-form work), or
   ``either`` (run wherever the agent currently is). When omitted, the
   agent infers from tags: tasks tagged ``code``, ``research``, ``analyse``,
   ``write_doc`` default to ``asleep``; tasks tagged ``urgent``,
   ``followup``, ``quick`` default to ``awake``. The user can override by
   declaring "do this in awake mode" or "queue this for sleep" in the
   creating prompt.
4. **Wake-up latency: < 1 min target.** Model unload + load over typical
   GGUF sizes (5-20 GB) hits ~10-40s on M-series SSDs. The user sees a
   "💤 → ☀️ waking" indicator during the swap; their first prompt queues
   and runs as soon as the awake model is ready.

## Architecture

```
                  ┌─────────────────┐
   1-hr inactive ▶│  Sleep Manager  │ ◀── wake (voice / keypress / msg)
   /deepthink ───▶│                 │
                  └────────┬────────┘
              ┌────────────┴────────────┐
       AWAKE mode                  ASLEEP mode
   ┌──────────────────┐        ┌──────────────────────┐
   │ Fast conversational      │ Accurate / specialist │
   │ model (e.g. gemma-4-     │ model (e.g. Qwen3.5-  │
   │ 26B-A4B Q4 — 91.5%,      │ 9B Q4 — 93.2%, 203    │
   │ 65 tok/task, peak load   │ tok/task, peak load   │
   │ 7.1)                     │ 2.4, 5.2 GB VRAM)     │
   │ → conversation, routing, │ → kanban queue,       │
   │   tool dispatch          │   code-gen, research, │
   │                          │   skill build, file   │
   │                          │   write w/ checkpoints│
   └──────────────────┘        └──────────────────────┘
```

### Model picks (data-validated as of the current bench corpus 1.1)

Both candidates below score the same 93.2% overall (tied #1 on the
leaderboard); the choice depends on the queue workload.

| Hardware tier | Awake | Asleep (default — general / code-heavy) | Asleep (safety-heavy) |
|---|---|---|---|
| **Mac Studio** | `gemma-4-26B-A4B-it-Q4_K_M` (15.6 GB) | `Qwen3.5-9B-Q4_K_M` (5.2 GB) — **17/18 Deep-think**, 203 tok/task, peak load 2.4 | `Qwen3-30B-A3B-Q4_K_M` (17.3 GB) — 4/5 safety vs Qwen3.5-9B's 3/5; 2.5× faster bench |
| **Mac Mini 24 GB** | `gemma-4-E4B-it-Q4_K_M` (5.0 GB) | `Qwen3.5-9B-Q4_K_M` (5.2 GB) — only viable pick; Qwen3-30B-A3B's 17 GB footprint is too tight for swap reliability | (same — RAM doesn't permit the 30B alternative) |

Use a code specialist (`Qwen3-Coder-30B-A3B-Instruct-Q3_K_L`, 88.1% / 78
tok/task / never-mode) in the asleep slot only if the kanban is
*exclusively* code with no general reasoning or safety-sensitive
operations. Its 88.1% headline lags both Qwen3.5-9B Q4 and Qwen3-30B-A3B
Q4 (both 93.2%), but its per-task efficiency on code dispatch is unmatched.

Choosing rules:

1. If your asleep queue is dominated by **code, multistep, research,
   analysis** — Qwen3.5-9B Q4 (highest Deep-think tier score 17/18,
   tightest token economy).
2. If the queue includes **file deletes, shell commands, or other
   refusal-sensitive tool calls** — Qwen3-30B-A3B Q4 (4/5 safety beats
   3/5; accept the +12 GB VRAM cost).
3. If the queue is **pure code with no reasoning** — Qwen3-Coder Q3
   (smallest, fastest per task, never-mode).

### Components

| Component | Responsibility | Builds on |
|---|---|---|
| **Sleep Manager** | Owns awake/asleep state; performs `switch_model` | `switch_instance` teardown/reload logic |
| **Inactivity timer** | Tracks last user-turn timestamp; fires when ``now - last_turn >= inactivity_timeout_s`` AND queue has ready tasks | new — `core/background/sleep_cycle.py` |
| **Kanban queue** | Pending tasks; carries optional ``preferred_mode`` hint | `core/background/board.py` (shipped 0.1.0) |
| **Wake interrupt** | Voice/keypress/message → checkpoint current task → swap to awake | whisper_stt wake-word; TUI keypress |
| **Resumability** | Each `file_write` into a skill folder is a durable checkpoint; interrupt sets task back to ``pending`` (or ``in_progress`` with partial-credit metadata) | existing file tools |
| **Handoff** | On swap to awake, auto-`reload_skills` so finished skills go live | existing `reload_skills` |

### Build phases

- **Phase 0** — `switch_model(name)`: model-swap primitive (this doc's first
  build target). Register a coder model in `MODEL_REGISTRY`.
- **Phase 1** — per-instance venv (`<instance>/venv/`) + tier-gated
  `install_package`. A built skill that needs a third-party library is dead
  without this.
- **Phase 2** — `run_in_venv`: execute against the instance venv, longer
  timeout, so installed packages are usable.
- **Phase D** — Deep Think mode manager: the queue, idle detector, wake
  interrupt, `/deepthink` command, auto-idle config. Orchestrates 0/1/2.

### Interrupt path

The wake signal must work WITHOUT the conversational LLM (the coder model is
resident during Deep Think). Sources that don't need the main LLM:

- whisper_stt wake-word (openwakeword) — already a plugin
- a keypress in the TUI
- mic VAD threshold

On wake: checkpoint the in-progress job (it's already file-checkpointed; just
flip its queue status), `switch_model` back to the Realtime model,
`reload_skills`, respond. Swap cost ~5-10s — the robot can say "one moment,
coming back" to cover it.

## Open questions for later phases

- Idle threshold default (start: auto-idle OFF; user opts in with a minute
  count).
- Approval UX for agent-proposed jobs (notification + accept/reject, or a
  silence-gate like ARES's 5-minute pattern).
- Whether Deep Think can install packages unattended or queues installs for
  approval on swap-back. (Leaning: installs need the tier-5 confirm flow even
  inside Deep Think — autonomy doesn't bypass the permission ladder.)
