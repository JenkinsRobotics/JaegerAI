# JROS daemon-architecture planning brief

> ## ⚠ STATUS — DEFERRED 2026-06-14
>
> Operator decision: JROS converges on **fused-mode** like Mochi
> and CC01. The split-mode / persistent-core / Tier-1 daemon
> architecture this brief proposes is **not** the current direction.
>
> What replaced it:
> * JROS adopted Jaeger app format 0.1 in fused mode (J1–J5B
>   commits, 2026-06-12 → 2026-06-14)
> * The chassis owns slot + atexit teardown in the TUI process
> * `--attach` plumbing was removed from `voice_loop` /
>   `messaging_gateway` / `tray/macos.py` in J5C (2026-06-14) —
>   each plugin loads its own model and runs standalone
>
> What stays valid in the brief:
> * The four-tier model framing (Identity / Subagents / Hardware /
>   Surfaces) — still the right mental model for JROS's
>   long-term architecture, just not the chassis it ships on today
> * The hardware-node lifecycle requirements — covered by
>   format 0.1's `Supervisor` + `[[node]]` manifest entries
>   (see Mochi's adoption for the working pattern)
>
> Why archived rather than deleted: the brief captures real
> operator framing + four-tier reasoning that future split-mode
> work (e.g. when JP01 real-time motor PID forces process
> isolation) will want to re-read. Keep as historical artifact.

**Date:** 2026-06-11
**Audience:** an LLM-driven planning / design agent (or a senior
engineer) who will produce a deeply-considered migration plan for
JROS's process / lifecycle architecture.
**Scope of the WORK:** PLAN ONLY.  Do not write production code in
this round.  Operator gates daemon-architecture changes behind
explicit approval (see "Approval gate" at bottom).
**Source repos to read:**
- `/Users/jonathanjenkins/GITHUB/JROS`       (the target)
- `/Users/jonathanjenkins/GITHUB/Mochi`      (the reference — its
  supervisor / config-driven multi-process model is the pattern
  the operator wants partial inspiration from)

---

## 0. Mission for the planning agent

Produce a CONCRETE, file-level migration plan that takes JROS from
its current architecture toward a **four-tier process model**:

  Tier 1 — Identity Daemon         (one process, must be single)
  Tier 2 — Subagent processes      (spawned on demand or persistent)
  Tier 3 — Hardware nodes          (always-on, real-time flavor,
                                     supervisor-managed lifecycle —
                                     ON / OFF / RESTART like Mochi)
  Tier 4 — Operator windows        (Mochi-style supervised
                                     subprocesses)

The plan must answer:

1. Which JROS code lands in which tier?  (file-level, with line
   citations if you find concrete boundaries.)
2. What IPC protocol carries each cross-tier boundary?  (Hermes
   in-process for Tier 1?  ZMQ for Tier 3 ↔ Tier 1?  Custom?)
3. How does Tier 3's "node lifecycle" API work (the
   ON/OFF/RESTART/STATUS that operator specifically asked for)?
4. What's the migration sequence — what ships first, what later,
   what's reversible, what's a one-way door?
5. Where are the failure modes?  Identity coherence under network
   partition?  Subagent orphans?  Hardware node restart while
   primary is mid-turn?
6. What metrics + observability does each tier need?
7. What operator-facing surfaces does the plan introduce / change?

The plan is a DOCUMENT.  Not code.  Operator reviews + approves the
document before any implementation commit lands.

---

## 1. Operator's own statements (verbatim)

These are the operator's words.  Treat them as design constraints.

> *"i want a single overall agent feel … like a unified agent
> across instances … but it doesn't necessarily mean only one
> process … be subagents … or maybe nodes for hardware is
> generated for local real time performance etc … idk"*

> *"hardware nodes might be turned on, off, restarted, etc similar
> to mochi"*

> *"the app should act like a single instance … other apps have
> floating windows but only one app icon and they all close
> together"* (this was about Mochi, but the same instinct applies to
> JROS — UI surfaces shouldn't proliferate as separate Dock items)

> *"i closed the application and the windows are still up"* (the
> "I close the app and things die together" expectation extends to
> the JROS hardware nodes — operator wants OFF/RESTART to mean what
> they mean)

---

## 2. Background — Mochi today (the reference pattern)

The planning agent should read `/Users/jonathanjenkins/GITHUB/Mochi`
directly to ground anything below.  Key facts as a quick orient:

### Launch flow

```
python main.py                                ← supervisor
  ├─ subprocess: transport/broker.py          ← ZMQ XPUB↔XSUB proxy
  ├─ subprocess: nodes/animation/node.py      ← animation node
  ├─ subprocess: agent/llm/node.py            ← LLM node (optional)
  └─ subprocess: gui/mochi_companion.py       ← Qt companion
        ↑
        all four talk over the broker
        (tcp://127.0.0.1:5555 / :5557)
```

### Critical implementation details Mochi ships today

- **`config.yaml`** declares `infrastructure:` (broker addresses,
  monitor address) + a `plugins:` list.  Each plugin entry has
  `id`, `type`, `entry` (or `module`), `cwd`, `config_path`,
  `enabled: true|false`.
- **`core/plugin_registry.py`** parses that config into PluginSpec
  objects.  Builds the launch command (Python `-m module` or
  `python entry.py`), sets cwd, injects env vars.
- **`main.py`** filters specs by `enabled`, launches the broker
  first, then loops through specs spawning each via
  `subprocess.Popen`.  Then `wait()` until ^C.
- **`HostMonitor`** at `tcp://127.0.0.1:5560` (REP socket) caches
  health/meta/event messages from every plugin so other tooling can
  query "is the animation node alive?" without each one
  subscribing.
- **Mochi has no daemon model.**  When `main.py` dies, everything
  dies.  The recent commit `1006dc1` moved Mochi's mini-window out
  of subprocess and into in-process (single Dock icon, closes with
  parent) — Mochi is consciously moving SLIGHTLY less multi-process
  for operator UX.

### What Mochi gets right (worth borrowing for JROS Tiers 3+4)

- **Config-driven node enable/disable** — operator flips a yaml
  field, no code change required.
- **Crash isolation per plugin** — animation node crash doesn't
  take down the LLM node.
- **HostMonitor pattern** — single REP socket where ANY consumer
  asks "what's alive, what's reporting health" without each
  consumer needing its own SUB.
- **No hidden processes** — `top` shows you exactly what's running.
  Operator can `ps aux | grep mochi` and reason about it.

### What Mochi gets wrong (don't repeat in JROS)

- **No persistence across launches.**  Every restart = re-spawn
  everything from scratch.  This is fine for Mochi (demo toy) but
  wrong for JROS (the agent's identity = continuous state).
- **No "soul" plugin.**  All plugins are peers.  JROS needs ONE
  plugin to be the identity daemon and the rest to serve it.
- **No persistent process beyond main.py's lifetime.**  No daemon.

---

## 3. Background — JROS today

The planning agent should read `/Users/jonathanjenkins/GITHUB/JROS`
directly.  These are the headline facts.

### Layout (verified against `git ls-files` 2026-06-11)

```
jaeger_os/
├── agent/
│   ├── loop/
│   │   ├── jaeger_agent.py        (882 lines — THE loop)
│   │   ├── runtime_bridge.py      (414 — voice/avatar/state bridge)
│   │   ├── callbacks.py
│   │   ├── interrupt.py           (139 — interruptible_call,
│   │   │                            disarm_interrupt race fixed
│   │   │                            in 4dd094d)
│   │   └── loop_backstop.py
│   ├── adapters/                  (anthropic, openai, hermes_xml,
│   │                                local_llama, mlx)
│   ├── dialects/                  (chatml, gemma, harmony, llama3,
│   │                                mistral, detect.py)
│   ├── tools/                     (31 py files: speak, listen,
│   │                                vision, browser, web, code,
│   │                                files, memory, scheduling,
│   │                                todo, identity_tools,
│   │                                delegation, skills,
│   │                                skill_market, background,
│   │                                deepthink_tools, board,
│   │                                avatar, models, packages,
│   │                                plugins, time_and_math, meta,
│   │                                remote, host, credentials,
│   │                                diagnostics, bench)
│   ├── prompts/                   (assemble, context_blocks,
│   │                                context_refs, prompts,
│   │                                reflection, rules, synthetic)
│   ├── runners/
│   │   └── thinking_runner.py
│   ├── background/                (board, cron_runner,
│   │                                deep_think, processes)
│   ├── schemas/
│   ├── parsing/                   (schema_sanitizer.py)
│   ├── skill_registry/            (11 py files)
│   └── personas/lilith/           (the persona)
└── (other top-level dirs)

apps/                              (recent — operator-launchable)
├── tray/                          (Tray Phase 1)
├── voice/                         (Voice Phase 2 — --attach flag)
└── (more in flight)

dev/scripts/                       (operator utilities)
dev/tests/
dev/docs/
docs/                              (this brief lives here)
launch                             (shell wrapper)
launch.py                          (Python entry)
install.sh
```

### Critical implementation details JROS ships today

- **Entry points** — `./launch` shell wrapper sources venv then
  invokes `launch.py` or `python -m jaeger_os.…`.  Single-process
  is the default.  Tray app + Voice CLI are SEPARATE entry points
  added recently with `--attach` semantics.
- **`docs/agent_refactor_phase_0.md`** describes the phase-1
  surface pinned in `jaeger_os/agent/__init__.py`.  Phases 2-8 are
  partially landed; planning agent should verify against actual
  code, not the doc.
- **Multi-instance is the design assumption** — `JaegerAgent`'s
  docstring states "every running context constructs its own
  JaegerAgent."  Deep think, voice loop, scheduler each spawn their
  own instance.  But they're all IN-PROCESS today.
- **Interrupt model** — daemon-thread + `Event`-poll cancellation
  + abandon.  See `loop/interrupt.py`.  The `disarm_interrupt` race
  was a real bug fixed in commit `4dd094d`; planning agent should
  consider whether process boundaries make that class of bug
  easier or harder to introduce.
- **Hermes router** — JROS already has an in-process message bus.
  Whether to keep using Hermes for Tier 1 internal IPC OR replace
  with ZMQ for cross-tier IPC is one of the planner's open
  decisions.
- **Recent `--attach` experiments** are the operator's early
  attempts at the daemon model, but it's piecemeal:

  ```
  17ec780  Messaging gateway: additive --attach flag (Option C)
  d14d00d  Tray: 'Open Voice' auto-passes --attach when daemon is up
  fbf4658  Strengthen system prompt: never claim a bug or a
           successful tool call without evidence
  8962027  Voice Phase 2 (minimal): additive --attach flag
  49d30de  Tray Phase 1: add Voice + GUI launchers to the menu
  ```

  Operator-noted this is mid-experiment.  The planner is invited to
  rationalise into a single config-driven model.

### What works today

- Single-process model is genuinely simple for development.  `./launch`
  + a debugger + the agent's foreground stdout/stderr is a fast loop.
- Voice + animation + agent share memory, no IPC tax on tool calls.
- `agent/__init__.py` already pins the public surface so internal
  reshuffles don't ripple.

### What's painful today

- Operator close terminal / ^C → conversation history gone, models
  unload, restart pays full warmup tax.
- Tray + Voice CLI + GUI launcher each had to invent their own
  `--attach` wiring rather than using a shared daemon-client
  contract.
- Hardware node integration (animation, voice) is mid-split — some
  bits in-process, some in their own subprocess — without a
  consistent declaration mechanism.
- Operator can't easily disable a hardware node without code edit
  (Mochi's `config.yaml` pattern doesn't exist for JROS).

---

## 4. The four-tier model the plan must implement

This is the design constraint the operator and I worked out
together.  Treat it as the SHAPE of the target architecture; the
planner fills in the file-level migration.

### Tier 1 — Identity Daemon  (one process, ALWAYS single)

```
Primary JaegerAgent (THE conversation, THE persona)
Loaded primary LLM (Gemma — slow to warm)
Conversation memory + history
Tool registry + routing
Persona state (Lilith mood, current scene)
Hermes router for everything below
```

**Identity-bearing.**  Crash this → identity gone, full restart.
The "soul" of JROS.

### Tier 2 — Subagent processes  (spawned on demand or persistent)

```
Research subagent       — heavy web crawl, different model
Code execution subagent — sandboxed, isolated crash domain
Deep-think subagent     — long context, doesn't block main
Vision-reasoning subagent — own CUDA stream
Long-task subagent      — survives main turn boundary
```

**HANDS, not separate beings.**  Primary agent calls them through
delegation tools.  They have NO independent identity — they return
results to the primary, which speaks for them.  Multiple primary
models could be running here (Gemma in Tier 1, Claude in a
research subagent, DeepSeek in a code subagent).

Three implementation modes the planner picks per subagent:

- **in-process subagents** (today, via `agent/tools/delegation.py`)
  — cheap call, shares Tier 1 model
- **subprocess subagents** — own model, own memory, doesn't block
  Tier 1
- **MCP subagents** — talks to an external server over the MCP
  protocol

Mature systems use all three depending on the task.

### Tier 3 — Hardware nodes  (always-on, real-time flavor)

```
Animation node          — frame-rate guarantees (already exists)
Voice I/O node          — low-latency audio callbacks
Motor controller        — PID loop at 1kHz (cannot share Python GC
                          with anything else; GC pauses break PIDs)
Vision/camera node      — its own CUDA stream + frame budget
IMU / sensor stream     — 100Hz+ stream, can't be paused
LED / display node      — refresh-rate locked
```

**Real-time / GC-isolated.**  Hard-real-time (motor PID, IMU
stream) → ideally not even Python — a Rust/C node speaking the
same IPC protocol.  Python orchestrates; Rust runs the loop.

**Operator-specified lifecycle requirement (verbatim):**

> *"hardware nodes might be turned on, off, restarted, etc similar
> to mochi"*

This is the headline new requirement.  The plan must include a
**node lifecycle API** that mirrors Mochi's plugin enable/disable
pattern.  Concretely:

- A config (yaml or similar) declares each hardware node:
  - `id`, `entry` / `module`, `enabled: true|false`, runtime
    parameters
- A supervisor (Tier 1-internal, or a separate process the planner
  argues for) can ON / OFF / RESTART individual nodes without
  restarting Tier 1
- An OPERATOR-FACING surface (CLI? tray? agent tool?) exposes
  these controls
- Each node publishes health (Mochi-style) so the supervisor knows
  when a node has crashed vs. is intentionally OFF
- A node restart MUST NOT crash Tier 1 mid-turn — graceful
  degradation when a node disappears

### Tier 4 — Operator windows  (Mochi-style supervised subprocesses)

```
TUI / avatar / tray / voice panel / diagnostics — Mochi-style
supervised subprocesses, attach over IPC.
```

Already partially in flight (Tray Phase 1, Voice --attach).  Plan
should consolidate the piecemeal `--attach` flags into a single
config-driven `windows:` list mirroring Mochi's `plugins:` list.

---

## 5. The two rules that make this feel like ONE agent despite ~10 processes

**Rule 1: Only Tier 1 ever speaks as the agent.**

The agent says "I'll go research that" — but the actual research
happens in a Tier 2 subagent.  The user never hears from the
subagent directly.  The primary speaks for the results.

**Rule 2: All state of record is in Tier 1.**

Subagents are stateless workers.  Hardware nodes are stateless
drivers (they expose current readings, they don't *remember*).
Windows are stateless views.  Memory + conversation + persona all
live in Tier 1 only.

That's how Anki Vector / EMO / ROS-based robots / Claude itself
feel like one being despite being many processes.  The plan must
enforce both rules at the architectural level — not by convention,
by API shape.

---

## 6. Anti-patterns the plan must avoid

The operator and I called these out explicitly:

1. **Making everything a subprocess because it "feels more modular"**
   — that's the Mochi temptation pulled to an extreme.  Mochi can
   afford it because every plugin is stateless.  JROS can't because
   Tier 1's state IS the agent's identity.

2. **Letting subagents speak as the agent** — "I'm the research
   subagent" is a UX failure.  All voice/text output runs through
   Tier 1's persona layer.

3. **Distributing canonical state** — only Tier 1 owns the
   conversation history, the persona state, the loaded primary
   model.  Other tiers can have READ-ONLY caches but must defer to
   Tier 1 for writes.

4. **Daemon arch shipped without operator approval** — per the
   standing rule, the plan does NOT ship code in this round.  Plan
   first.  Approve.  Then implement in small reviewable steps.

5. **"Phantom systems" doc drift** — the plan must NOT describe
   APIs, files, or protocols that don't exist yet without labeling
   them `(planned)`.  Recent reviews caught me writing fiction in
   review briefs.  Don't repeat.

6. **Breaking the existing `--attach` flow without a transition** —
   the Tray + Voice CLI + GUI launcher already work.  Migration must
   be additive: new config-driven `windows:` model can be opt-in
   while the existing entry points keep working.

---

## 7. Specific JROS code → tier mapping (starting hypothesis)

The planner should VERIFY each of these against the actual code +
adjust.  These are starting hypotheses, not statements of fact.

| Existing JROS code | Hypothesised tier | Why |
|---|---|---|
| `jaeger_os/agent/loop/` (whole loop) | Tier 1 | The agent loop IS the identity |
| `jaeger_os/agent/adapters/` | Tier 1 | Adapter calls happen inside Tier 1 |
| `jaeger_os/agent/dialects/` | Tier 1 | Same — wire-format translation per call |
| `jaeger_os/agent/tools/` (most) | Tier 1 | In-process tool dispatch |
| `jaeger_os/agent/tools/delegation.py` | Tier 1/2 bridge | The MECHANISM for Tier 2 calls |
| `jaeger_os/agent/tools/code.py` | Tier 2 (subprocess) | Code execution wants sandbox |
| `jaeger_os/agent/tools/vision.py` | Tier 2 (subprocess) | CUDA stream isolation |
| `jaeger_os/agent/tools/browser.py` | Tier 2 (subprocess) | Browser process is heavy |
| `jaeger_os/agent/tools/deepthink_tools.py` | Tier 2 | Long-context, doesn't block main |
| `jaeger_os/agent/background/deep_think.py` | Tier 2 candidate | Background work |
| `jaeger_os/agent/background/cron_runner.py` | Tier 1 (scheduler) | Triggers IN Tier 1 |
| `jaeger_os/agent/background/processes.py` | Tier 1 (registry) | Subprocess registry |
| `jaeger_os/agent/prompts/` | Tier 1 | Prompt assembly per turn |
| `jaeger_os/agent/personas/lilith/` | Tier 1 | THE persona = identity |
| `jaeger_os/agent/runners/thinking_runner.py` | Tier 1 | Driver inside the daemon |
| `jaeger_os/nodes/animation/` (if it exists) | Tier 3 | Already split, frame-rate locked |
| `apps/tray/` | Tier 4 | Operator window |
| `apps/voice/` | Tier 4 (with Tier 3 voice node) | UI + Hardware split |
| `apps/gui/` | Tier 4 | Operator window |

Some of these claims need verification — planner should
`grep -r` and confirm before committing to them in the plan.

---

## 8. Hardware-node lifecycle API — the planner's specific homework

This is the operator's headline new requirement.  Design it
carefully.

Things the API must support:

1. **Declarative config** — operator declares hardware nodes in a
   yaml file (or equivalent) with `id`, `entry`, `enabled`, params
2. **`enable`/`disable` per node** — without restarting Tier 1
3. **`restart`** — kill + respawn a single node, gracefully
4. **`status`** — operator queries which nodes are alive / which
   are reporting errors
5. **Health broadcasts** — each node publishes liveness so the
   supervisor + tier-1 know when nodes are stale
6. **Crash-detection + auto-restart policy** — opt-in per node
7. **Graceful Tier-1 degradation** — if motor node dies, Tier 1's
   `motor.*` tool calls should fail gracefully, not crash the agent

Open questions the planner must resolve:

- WHERE does the node-supervisor live?
  - (a) Inside Tier 1 daemon as a thread / asyncio task
  - (b) Separate supervisor process (Mochi-shaped)
  - (c) Inside the existing Hermes router

- WHAT IPC carries the lifecycle commands?
  - REQ/REP socket per node?
  - Single supervisor REQ/REP that fan-outs?
  - Agent-tool wrappers (`enable_node`, `restart_node`)?

- WHAT happens to ongoing tool calls when a node restarts mid-turn?
  - Auto-retry?
  - Surface error to the agent ("motor offline, retry?")?
  - Pause turn until node back?

- HOW does the operator surface look?
  - CLI: `jros node restart animation`?
  - Tray menu item per node?
  - Agent tool: `set_node_state(node='animation', state='off')`?

The plan should propose answers and explain trade-offs.

---

## 9. Open questions the planner should ask the operator (or assume sensible defaults for)

Before finalising, surface these for operator confirmation:

1. **Tier-1 daemon process model**: one Python process for life, or
   process-per-session with conversation rehydration from disk?
   (Most likely answer: one process for life, plus disk-based
   conversation persistence as a separate concern.)

2. **Subagent lifecycle**: persistent (warm pool) vs spawn-on-demand?
   Heuristic by use frequency?

3. **Hardware-node restart policy**: who decides when to restart?
   Agent (via tool call) vs operator (via tray/CLI) vs auto
   (supervisor on crash)?  Mix?

4. **IPC**: keep Hermes for Tier 1 internal + add ZMQ for
   cross-tier, OR switch everything to ZMQ for uniformity?
   Operator-facing answer probably depends on Hermes's current
   maturity in the codebase — verify.

5. **Configuration mechanism**: one yaml (a la Mochi's `config.yaml`)
   vs split (one per tier) vs already-existing
   `.jaeger/instance/`-style per-machine config?

6. **Voice node split**: currently mid-split (in-process today,
   subprocess later).  Should the plan force the split immediately
   or leave voice in Tier 1 for now as a pragmatic interim?

7. **Backwards compatibility**: how much of the existing `./launch`
   single-process flow should keep working?  Total bridge or
   one-way migration?

8. **MCP integration**: does the plan treat MCP servers as a
   variant of Tier 2 subagents, or as a separate tier?

---

## 10. Output the operator expects from the planner

A single markdown document, ~600-1200 lines, structured as:

1. **Executive summary** — five sentences max, what the plan does
2. **Four-tier mapping** — each existing JROS file/dir → its tier,
   with justification
3. **Hardware-node lifecycle API spec** — config schema, IPC
   protocol, operator-surface examples
4. **IPC architecture** — Hermes vs ZMQ decisions, message shapes
5. **Migration phases** — what ships first, what later, dependency
   graph
6. **Failure modes + mitigations** — what could go wrong, what the
   plan does about it
7. **Operator-facing changes** — what the operator sees that's new
8. **Observability** — health, logs, status per tier
9. **What this plan does NOT do** — explicit out-of-scope list
10. **Open questions + recommendations** — items needing operator
    sign-off before implementation begins

NO production code in the plan output.  Schema sketches + IPC
message shapes + config YAML examples ARE OK and encouraged.

---

## 11. Standing rules the planner must honour

These come from the operator's memory and prior reviews.  They
apply to the plan AND any future implementation.

1. **Daemon-arch changes need explicit operator approval BEFORE
   implementation.**  The plan is the proposal; operator says go
   before code lands.  Do not bypass this rule.

2. **Convention docs may not describe behaviour the runtime
   doesn't implement.**  Anything in the plan that refers to "we
   will add X" must be labeled `(planned)` and dated.  Don't ship
   fiction.

3. **STATUS.md (or equivalent) must stay truthful.**  If the plan
   recommends shipping STATUS-shaped docs, they must be kept in
   sync with code in the same commit.

4. **Never push without explicit OK.**  Local commits + tags fine;
   `git push` requires per-turn approval.

5. **No back-compat shims pre-1.0.**  Drop legacy code paths.  But
   the daemon migration may need a transitional bridge during
   migration — call those out explicitly with a removal date.

6. **No Claude co-author trailer in commits.**

7. **Commit at milestones, not after every pass.**

---

## 12. How to start

Suggested first moves for the planner:

1. **Read both repos.**  `Mochi/` for the supervisor pattern;
   `JROS/` for the target.  Focus areas in JROS:
   `jaeger_os/agent/__init__.py`, `jaeger_os/agent/loop/`,
   `jaeger_os/agent/tools/delegation.py`,
   `jaeger_os/agent/background/`, `apps/`, `launch.py`.
2. **Verify the file-mapping hypothesis in Section 7.**  Some of
   those may be wrong; correct them.
3. **Audit the recent `--attach` commits.**  Read
   `git log --oneline | grep -E "attach|tray|gateway"` to find
   them.  Their existence is fact; their final shape is up to the
   plan.
4. **Sketch the hardware-node lifecycle API first.**  It's the
   biggest open design question + the operator's headline ask.
   Get this right and the rest of the plan flows.
5. **Write the plan to `docs/JROS_DAEMON_ARCH_PLAN.md`** (sibling
   to this brief).  Operator reviews + approves.  Then — only then
   — implementation begins in a separate review-tracked branch.

## 13. Approval gate

The planner does NOT begin implementation without an explicit
operator green light on the finished plan document.  If the
planner is tempted to "just start a tiny refactor to clean
something up" while writing the plan — don't.  The plan is the
deliverable.  Ship it, get approval, then implement in measured
phases per the plan.

---

End of brief.  Read Mochi.  Read JROS.  Write the plan.  Hand it
to the operator.  Wait for approval.
