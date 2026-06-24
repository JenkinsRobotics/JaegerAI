# JROS Agent Loop — review brief

**Date:** 2026-06-10
**Version:** 0.5.0
**Scope:** **agent loop only** (`jaeger_os/agent/`).  Voice, safety,
skill tree, node-expansion get their own briefs after this one.
**Animation node is INTENTIONALLY out of scope** — Mochi is the
animation pipeline testbed.
**Author of the code under review:** Claude, working with the operator
**Audience:** an LLM-driven code-review tool, or a senior reviewer
**Goal of this document:** focus the reviewer on what the operator
considers JROS's CRITICAL functional half — the cognitive loop
that drives every other subsystem.

### Hard out-of-scope for this review

Do not propose changes to:

1. **App / daemon architecture** — single-process vs multi-process,
   plugin model, broker topology, process supervision.  This is
   queued as a separate (last) review and any change to it
   requires an explicit plan + operator approval before
   implementation.  If you have observations on this, FLAG them as
   "for the future daemon-arch review" rather than acting on them
   here.
2. **Animation node / Lilith face / avatar pipeline** — Mochi is
   the dedicated testbed.  Findings about how the agent CALLS the
   animation node are in scope; the animation pipeline itself is
   not.
3. **Vision / motor pipelines** — not functional yet.  Their
   stubs exist but reviewing them now is premature.
4. **Plan-doc renames or restructuring** — `docs/0.5.0_*` files
   shape work in flight; don't suggest they be moved or merged
   without a separate proposal.

Copy-paste this entire file into the review tool's input.

---

## 0. Prime the pattern search — lessons from prior reviews

The Mochi review surfaced 5 real bugs we'd missed.  The VoiceLLM
review surfaced **even better findings, including the operator's
worst possible bug class**: silent permanent failure in a
daily-driver path.  The operator wants the JROS reviewer to
**look for the JROS analogs of EVERY VoiceLLM finding** and
implement equivalent improvements.  The mapping table below is
the priority queue for this review — flag every JROS analog
even if it's a near-miss.

### Hard prior — the four VoiceLLM findings most likely to recur in JROS

| VoiceLLM finding | JROS analog to hunt | Why JROS is exposed |
|---|---|---|
| **Context overflow → silent permanent mute.** LLM thread dies on `ValueError` raise from `create_chat_completion`, `finally` appends empty assistant turn, every subsequent turn fails identically until restart. Only manifests in long sessions. | `JaegerAgent.run_turn`: what happens when `ContextOverflow` is raised mid-turn?  Does the loop's `finally` (if any) leave `self.messages` in a state that *deterministically* re-fails?  Does the operator see ANY surfaced error, or does the agent silently stop responding?  This is the bug-class the operator most cares about because daily-driver use produces long sessions. | JROS has more context-consumers (skills, MCP, deep-think, runtime_bridge) and a bigger system prompt + persona context.  Multi-instance design means the same overflow can happen in voice OR deep-think OR scheduler simultaneously. |
| **Metrics never measure listen/STT time** — all timestamps set at receive-of-`stt.text`, so the entire silence-hangover + transcription pass is invisible.  The project's "feels faster" claim is unverifiable from its own data. | Whatever JROS records per-turn — is each timestamp recorded at the EARLIEST point that work begins, not the receive point in the orchestrator?  Audit `runtime_bridge.py` + any metrics writer for "we record this when the message arrives" pattern. | JROS has more inter-node hops than VoiceLLM (animation node, vision, motor).  Each hop is a place where "timestamp at receive" loses real latency. |
| **Bus is a work queue, not pub/sub** — `tts.audio_chunk` subscribers are architecturally unreachable because `queue.Queue.get()` removes the message; second subscriber would steal from the orchestrator. | JROS uses ZMQ which IS real pub/sub, so this exact bug doesn't apply.  BUT — look for places where ZMQ subscribe patterns are wrong: is anything assumed reachable that isn't, e.g. multi-subscriber on a PUSH/PULL socket? | The architecture is right but the wiring may not be. |
| **Doc-as-fiction in STATUS.md + architecture docs**, where the project's stated workflow is "fresh LLM reads docs first" — every drift item is a planted false memory. | JROS has FAR more docs than VoiceLLM (`docs/0.5.0_*` plans, ROADMAP files, SKILL_TREE.md, STATUS.md).  Audit them.  Each unbuilt-but-confidently-described item is a session-time tax. | JROS is the operator's primary repo for LLM-assisted work.  Doc fiction here hurts the most. |

### Watch for the SAME pattern families Mochi surfaced too:

| Family | Mochi instance | JROS agent loop has the same risk because… |
|---|---|---|
| **Worker-thread + main-thread lifecycle** | `HealthService.stop()` closed the ZMQ SUB socket from the main thread while the worker was in `recv` | The agent runs adapter HTTP calls on **daemon threads** with an `Event`-poll cancellation pattern ([loop/interrupt.py](jaeger_os/agent/loop/interrupt.py)).  Race surface: cancel-while-streaming, multiple turns interrupting overlapping threads, stale heartbeat from abandoned daemon. |
| **Layout / state rebuild every tick** | Nodes-table tore down + rebuilt rows ~2x/sec, destroying click targets mid-press | Agent has periodic context refresh, scheduler ticks, deep-think pulses — anywhere shared state mutates on a timer, audit for "consumer iterates while producer mutates". |
| **Doc ahead of code** | Three convention docs described phantom tools / unwired fields | This is the highest-risk family in JROS — many `docs/0.5.0_*` plans, ROADMAP files, skill tree plans.  Each "plan ahead of implementation" gap is a future-you trust trap.  Call out every "described but not implemented" case. |
| **Smoke test asserting fake conditions** | Sprite handler "verified at t=0" — production `t` is never 0 | Any agent test that fakes the adapter (`FakeAdapter`, in-memory `Message` lists) — does it cover the real wire format + cancellation behaviour, or just the call shape? |
| **Schema without validator** | `schema:` version field in 167 yaml files, zero validators | `ToolDef`, `Message`, `ToolCall` are TypedDicts.  Are there runtime validators for tool argument shapes when models send malformed JSON?  What happens when a Gemma dialect emits a tool-call the dialect parser doesn't recognise? |

Just-fixed bug worth highlighting (commit `4dd094d`):
`disarm_interrupt` race — the voice loop captured a `self._voice`
reference that got nulled mid-turn, so the finally-block crashed
trying to disarm.  We patched the symptom (capture once, guard
the disarm).  **Look for the same pattern elsewhere** — anywhere
the agent stores a reference to a peripheral / adapter / channel
that can be hot-swapped from another thread.

---

## 1. What the JROS agent loop is

`JaegerAgent` is a **framework-free replacement for pydantic-ai** —
a Hermes-style tool-using agent loop that drives the entire JROS
robot.  It owns the `format → call → parse → dispatch` loop, the
turn budget, the cancel flag, the halt backstop, and the
observability hooks.  Adapters own wire-format translation +
the actual model call.

It is **stateful per turn** (running conversation, interrupt
event, signature-count dicts as loop backstops), and the design
assumption is **multi-instance**: deep-think, voice loop, and
scheduled tasks each construct their own `JaegerAgent` with their
own conversation.

The operator's framing for this review (verbatim):

> *JROS functional half is the agentic and voice pipelines and that
> is what needs to be finetuned and improved as much as possible.
> Any performance, organization, etc improvements.*

So the reviewer's job is **performance + organization + reliability**.
Skill expansion, vision, motor are out of scope here.

## 2. Why we're building it

| Audience | What they want |
|---|---|
| **Operator (Jonathan)** | A reliable, voice-fast, interruptible robot brain that drives Lilith's avatar + voice + tools, runs entirely local, and doesn't lose conversational context between turns. |
| **JROS as a system** | A clean cognitive layer that 8+ other subsystems (voice, animation, vision, motor, skills, background, scheduling, gateway) can target without each re-implementing turn lifecycle. |
| **Future contributors** | A readable Hermes-style agent loop without a framework dependency — adapter / dialect / tool layers are pluggable. |

The agent ABSORBED pydantic-ai's responsibilities in phases 1-8.
The migration plan lived at `docs/agent_refactor_phase_0.md`.

## 3. What's shipped (0.5.0, current state)

### Agent layer directory tree

```
jaeger_os/agent/            (cognitive core — review scope is THIS subtree)
├── __init__.py             ← public surface pin: Message / ToolCall /
│                              ToolDef / register_tool / ProviderAdapter
│                              / AgentCallbacks / AgentInterrupted /
│                              interruptible_call / JaegerAgent
├── loop/                   ← THE loop (5 files, 1900 lines)
│   ├── jaeger_agent.py     (882 lines — THE single biggest file)
│   ├── runtime_bridge.py   (414 — voice/avatar/state bridge to the loop)
│   ├── callbacks.py        (189 — AgentCallbacks observability hooks)
│   ├── interrupt.py        (139 — interruptible_call, StaleCallTimeout,
│   │                          on_heartbeat)
│   └── loop_backstop.py    (105 — semantic-failure detection,
│                              repeated-call signature dedup)
├── adapters/               ← provider abstraction (7 files)
│   ├── base.py             (ProviderAdapter ABC)
│   ├── anthropic.py        (Claude — primary cloud)
│   ├── openai.py           (OpenAI — fallback cloud)
│   ├── hermes_xml.py       (NousResearch Hermes XML — preferred local)
│   ├── local_llama.py      (llama.cpp — fallback local)
│   └── mlx.py              (Apple MLX — apple silicon)
├── dialects/               ← tool-call wire formats (8 files)
│   ├── detect.py           (autodetects which dialect a model speaks)
│   ├── chatml.py / gemma.py / harmony.py / llama3.py / mistral.py
│   └── _shared.py          (common parser primitives)
├── tools/                  ← tool surface (31 py files)
│   ├── _common.py / availability.py
│   ├── speak.py / listen.py / vision.py
│   ├── browser.py / web.py / code.py / files.py
│   ├── memory.py / scheduling.py / todo.py
│   ├── identity_tools.py / personas / delegation.py
│   ├── skills.py / skill_market.py
│   ├── background.py / deepthink_tools.py / board.py
│   ├── avatar.py / models.py / packages.py / plugins.py
│   ├── time_and_math.py / meta.py / remote.py / host.py
│   └── credentials.py / diagnostics.py / bench.py
├── prompts/                ← prompt assembly (8 files)
│   ├── assemble.py         (final prompt builder)
│   ├── context_blocks.py   (modular context slots)
│   ├── context_refs.py     (cross-context references)
│   ├── prompts.py          (top-level templates)
│   ├── reflection.py       (self-reflection prompts)
│   ├── rules.py            (the system rules block)
│   └── synthetic.py        (synthetic conversation generation)
├── prompt_assets/          ← markdown / yaml fixtures consumed by prompts
├── schemas/                ← TypedDicts + registries (5 files)
│   ├── message_types.py    (Message / ToolCall)
│   ├── tool_registry.py    (register_tool, get_tool, get_tools)
│   └── tool_schema.py      (ToolDef — the three renderers per tool)
├── parsing/                ← model-output parsers (3 files)
│   └── schema_sanitizer.py (the big one — fixes mangled JSON/XML)
├── runners/                ← high-level entry points (2 files)
│   └── thinking_runner.py  (driver for "think + speak" turns)
├── background/             ← long-running tasks (5 files)
│   ├── board.py
│   ├── cron_runner.py
│   ├── deep_think.py
│   └── processes.py
├── skill_registry/         ← skill catalog (11 files)
├── personas/lilith/        ← Lilith persona — primary character
└── skills/                 ← skill implementations (mostly empty
                              folders today; tree is reserved)
```

**Total agent subtree: ~120 py files** but most of `skills/` is
empty placeholders.  Real code mass: `loop/` (5) +
`adapters/` (7) + `dialects/` (8) + `tools/` (31) +
`prompts/` (8) + `background/` (5) + `runners/` (2) +
`schemas/` (5) + `parsing/` (3) + `skill_registry/` (11)
= ~85 active files.

### What ships today

**VERIFIED against actual code (verified by reading the files,
not just the docstrings):**

- **Single `JaegerAgent` class** in `loop/jaeger_agent.py` —
  882 lines, drives `format → call → parse → dispatch`.
  ✓ verified.
- **5 adapter files exist** — `anthropic.py`, `openai.py`,
  `hermes_xml.py`, `local_llama.py`, `mlx.py`.  ✓ verified.
- **`openai.py:171` explicitly says** "The adapter is intentionally
  thin — no retry / no fallback / no [streaming]; fallback belongs
  in `jaeger_os.core.runtime.cloud_errors`".  So fallback is NOT
  in the adapter layer — **reviewer should verify whether the
  cloud_errors module actually implements adapter fallback or if
  it's another phantom**.  ✓ verified the disclaimer, ✗ have not
  read cloud_errors.
- **5 dialect files exist** — `chatml.py`, `gemma.py`, `harmony.py`,
  `llama3.py`, `mistral.py` + `detect.py` + `_shared.py`.
  ✓ verified files exist; ✗ have not verified dialect autodetect
  actually works.
- **`interruptible_call` + `StaleCallTimeout` + `on_heartbeat`**
  all exist in `loop/interrupt.py`.  ✓ verified.
- **`disarm_interrupt` race fixed in commit `4dd094d`.**
  ✓ verified.
- **`@register_tool` decorations found: 2**, NOT 31.  The
  `tools/` directory has 31 py files but only **2 use the
  `@register_tool` decorator**.  Reviewer should investigate:
  are the other 29 tool files registered another way (factory,
  runtime, manifest), or are they un-registered scaffolding?
- **`AgentCallbacks` exists** in `loop/callbacks.py` (189 lines).
  ✓ verified file; ✗ have not verified every hook is wired.
- **Loop backstops** — `call_signature`, `semantic_failure_signature`,
  `loop_halt_reason` all exist in `loop_backstop.py`.  ✓ verified
  exports; ✗ have not verified they actually fire on runaway loops.
- **`ContextGuard` exists** in `util/context_guard.py`.  ✓ verified
  import; ✗ have not verified it actually catches overflows
  before the model call.
- **Skill registry** — 11 py files in `skill_registry/`.
  ✓ verified file count; ✗ have not verified runtime registration
  actually works.

**Claims I removed from earlier draft (caught by self-audit):**

- ❌ "Anthropic is primary cloud" — I fabricated this; no code
  designates a primary.
- ❌ "Hermes XML is preferred local" — same, fabricated.
- ❌ "31 tools via `@register_tool`" — actually 2.
- ❌ "Fallback chain when one fails" — openai.py disclaimer
  says fallback is NOT in the adapter layer.

### Recent commits (0.5.0)

```
4dd094d  0.5.0 fixes: disarm_interrupt race + clarify "speak me X" rule
84798d6  0.5.0: move core/background/ → agent/background/
317c67e  0.5.0: Mochi-style Lilith face + reorg fallout cleanup
ee54bec  0.5.0: jaeger avatar — see Lilith in action + fix manifest reader
0958a98  dev/docs: 0.5.0 walk-the-flow checklist
4544ce0  0.5.0: auto-state driver + --stream mode + --no-avatar opt-out
99bea1c  0.5.0: /sense/tts_chunk topic + TTSNode emits + lip sync wired
1e9a68a  0.5.0: Lilith persona + face script — 0.5.0 becomes visibly real
a8d4a3d  0.5.0 Track C+infra: AnimationNode auto-start at boot
f768fb7  0.5.0 Track C.7: set_avatar_state + play_timeline agent tools
```

## 4. Architecture / design pillars

These are **claims pulled from the `jaeger_agent.py` docstring**.
The reviewer should verify each one against the actual code.  I
read the docstring + file structure; I did NOT trace every code
path.

- **Loop owns the loop, adapter owns the wire** — per docstring;
  verify by checking `JaegerAgent.run_turn` doesn't construct HTTP
  requests directly.
- **`ToolDef` registers three renderers** (Anthropic / OpenAI /
  Hermes-XML formats) — per `agent/__init__.py` docstring;
  verify by reading `schemas/tool_schema.py`.
- **Multi-instance by design** — per `jaeger_agent.py` docstring
  ("Multi-instance use [...] is the design assumption — every
  running context constructs its own `JaegerAgent`"); verify by
  checking no class-level mutable state, no module-level locks
  scoped to the wrong granularity.
- **Cancellation is poll-based, not preemption** — `interrupt.py`
  docstring confirms daemon-thread + Event-poll + abandon
  pattern.  ✓ confirmed from file read.
- **Backstops layered** — `ContextGuard`, `loop_backstop`,
  `StaleCallTimeout`, `AgentInterrupted` all exist as files /
  classes; verify they actually fire under the claimed
  conditions.

## 5. What we know is unwired or planned but unimplemented

(Per the brutal-feedback rule from Mochi's review — flag the gaps
before the reviewer has to find them.)

| Item | Status |
|---|---|
| `docs/0.5.0_agent_reorg_plan.md` | Reorg landed; some Phase-3/4 polish items may be unimplemented |
| `docs/0.5.x_skill_tree_evolution_plan.md` | Many skill tree folders are empty placeholders (see `agent/skills/<category>/<skill>/`) |
| `docs/SKILL_TREE.md` | Skill manifest format described; runtime activation logic exists, but most skills are empty |
| `personas/lilith/avatar/faces/` | One face script today; rest is the framework |
| `dialects/` × `adapters/` matrix | Not every dialect tested with every adapter — some combinations may silently fall back |
| `runners/thinking_runner.py` | Single runner today.  Other planned runners (`voice_runner`, `bench_runner`) not landed |

## 6. What's NOT shipped — feature gap

| # | Feature |
|---|---|
| 1 | Adapter fallback policies — exists but configurable per-runner? per-call? |
| 2 | Per-tool circuit breakers (if a tool fails N times, suspend) |
| 3 | Conversation persistence across process restarts |
| 4 | Multi-agent coordination (delegation tool exists but no orchestrator) |
| 5 | Adversarial / safety filter layer ahead of tool dispatch |
| 6 | Cost telemetry per turn (tokens × provider) |
| 7 | Replay mode — re-run a saved turn against a different adapter for comparison |

## 7. What to develop FIRST

Operator's framing: **performance + organization + reliability** —
not new features.  My read for the next 5-10 commits (subject to
reviewer override):

### Priority A — split `jaeger_agent.py` (882 lines)

It's THE single biggest agent file.  Candidates: turn lifecycle,
tool dispatch, context management, prompt assembly hand-off,
interrupt + heartbeat plumbing.  But: the operator's "no churn"
preference means this should only happen if the reviewer agrees
the file is genuinely too dense — not as cosmetic refactor.

### Priority B — audit interrupt + heartbeat plumbing for `disarm_interrupt`-class bugs

We just fixed one of these.  How many more lurk?  Look for stored
references to peripherals / adapters / channels that can be hot-
swapped from another thread.  Look for finally-blocks that touch
state mutated elsewhere.

### Priority C — schema sanitizer + dialect detection edge cases

When a model emits a malformed tool call (most common failure
mode in long sessions), what's the recovery path?  Today: silent
fallback?  Re-prompt with a "your last tool call was malformed"
nudge?  Operator never sees the failure?

### Priority D — adapter fallback chain audit

Multi-adapter is the design assumption.  Is the fallback policy
clear?  Per-turn?  Per-failure-type?  Does it leak provider
quirks (e.g. Anthropic-style stop sequences leaking to OpenAI)?

### Priority E — `loop_backstop` validation

Are the signature dedup + halt detection actually catching
runaway loops in practice?  Or do they fire false positives that
the operator has had to work around?

## 8. Specific questions for the reviewer

### A. The 882-line loop file

1. **`jaeger_agent.py` is 882 lines.**  Is it actually too dense for
   one file, or is it appropriately a single state machine that
   would lose clarity if split?  Specific candidates if split:
   - turn state machine
   - tool dispatch + ToolDef render
   - prompt assembly hand-off
   - interrupt + heartbeat plumbing
   - context-overflow handling
2. **Multi-instance assumption** — every running context constructs
   its own `JaegerAgent`.  Is anything in the loop accidentally
   global / class-level that breaks that?
3. **Per-turn state mutation** — `self.messages` is mutated as the
   loop runs.  Is there a clean way to roll back a partially-
   executed turn on `AgentInterrupted`, or does cancelling mid-
   turn leave the conversation in an awkward state?

### B. Concurrency + lifecycle

4. **Interrupt model** — daemon-thread + Event-poll + abandon.  Are
   there places where the abandoned daemon thread can still mutate
   state that the next turn relies on?  Stack: HTTP socket
   buffers, callback firing AFTER cancel, partial tool-call parses.
5. **The `disarm_interrupt` race we just fixed** — same pattern
   elsewhere?  Look at `runtime_bridge.py` (414 lines), any
   place that stores `self._X = peripheral` and uses `X` later in
   a `try/finally`.
6. **`StaleCallTimeout` vs the SDK's own timeout** — do they race?
   What happens if the SDK times out at second 599 and we time
   out at second 30?
7. **Background tasks** (`background/`) — deep_think, cron_runner,
   processes, board.  Do they share state with the foreground
   loop?  Locks?

### C. Adapter + dialect

8. **5 adapters × 5 dialects = 25 combinations.**  Which are tested?
   What happens for the untested combinations — silent fallback or
   loud error?
9. **`schema_sanitizer.py`** in `parsing/` — what's the model of
   "trustworthy enough to dispatch a tool"?  Where does the
   sanitizer fail closed vs fail open?
10. **`dialect/detect.py`** — autodetects the model's dialect.  What
    happens when detection is wrong?  Mid-session can it drift?

### D. Tools + skills

11. **31 tools** registered via `@register_tool`.  Are tool argument
    schemas validated at dispatch time, or only at parse time?
    Race: model emits a tool call → sanitizer accepts → dispatch
    receives args that don't match `ToolDef` → tool crashes inside.
12. **Skill registry** + runtime registration — 11 files in
    `skill_registry/`.  How does the agent learn about a newly-
    activated skill mid-session?
13. **Tool re-entrancy** — multi-instance is the design; same tool
    might dispatch from two `JaegerAgent` instances at once.
    Which tools assume single-instance?  `speak`, `listen`,
    `vision`, `host` are likely candidates.

### E. Performance — "feels slower than VoiceLLM"

14. Operator observation: VoiceLLM feels faster than JROS for the
    same voice task.  VoiceLLM is single-process, in-process bus,
    minimal abstraction.  JROS adds: bus topics + animation node +
    multi-tool routing + persona + avatar + context blocks.  Where
    is the latency budget actually going?  Profile-worthy spots?
15. **Adapter call latency** — is each turn paying for HTTP
    handshake to a local server (llama.cpp) that could be a
    persistent connection?
16. **Prompt assembly** — `prompts/assemble.py`.  How much work
    per turn?  Cache opportunities?

### F. Doc-ahead-of-code patterns

17. **`docs/0.5.0_*` files** — many.  Audit: which describe code
    that exists vs code that's planned?  Mark every gap.
18. **`docs/SKILL_TREE.md` + 11-file `skill_registry/`** vs **mostly
    empty `skills/<category>/<skill>/`** folders — what's the
    actual skill activation status?  Are any of those empty
    folders supposed to have code?
19. **`docs/agent_refactor_phase_0.md`** — referenced by
    `agent/__init__.py`.  How much of the multi-phase migration
    landed?  What got skipped?

### G. Forward direction

20. **Where would YOU start** if you were taking over for
    "performance + organization + reliability"?  Operator's order
    was: agent loop → voice → safety → skill tree → expansion.
21. **What's the biggest 3-month risk** in the agent code that
    would bite operationally?
22. **What looks over-engineered** that should die now?

## 9. Practical context

- Python 3.11+ (jaeger_os runs on operator's pyenv 3.13.7 — broken
  blake2 hashlib at startup is noise, not a blocker)
- macOS-first; Linux supported but secondary
- Local-first (Apple Silicon) — operator runs Hermes XML
  + Anthropic fallback
- 0.5.0 is the current branch tip; many `0.5.x_*` plan docs exist

To run + explore:

```bash
cd /Users/jonathanjenkins/GITHUB/JROS
./launch                                      # the whole agent
./launch --stream                             # token-stream mode
./launch --no-avatar                          # skip Lilith face
.venv/bin/python -m jaeger_os.agent.runners.thinking_runner --help
```

To audit code:

```bash
wc -l jaeger_os/agent/loop/*.py
ls jaeger_os/agent/{tools,adapters,dialects}
cat jaeger_os/agent/__init__.py
git log --oneline jaeger_os/agent | head -50
```

## 10. Output I want from the reviewer

**Operator's specific directive for this review (verbatim):**

> *"also for jros prefer have it implement the improvements from
> VoiceLLM"*

So this is not just a review — the reviewer is **expected to
implement** JROS-side equivalents of the VoiceLLM findings where
they apply.  Order:

1. **Section 0 hard-prior hunt first.**  The 4-row table at the top
   is the highest-priority work.  For each VoiceLLM finding, find
   the JROS analog and IMPLEMENT THE FIX in the same review round.
   The context-overflow-silent-mute bug is the operator's #1 worry
   for daily-driver use — if a JROS analog exists, fix it.
2. **Direct answers to Section 8 questions** — specific, actionable.
3. **A prioritised list of issues found** — severity × effort.
   Bugs first (especially `disarm_interrupt`-class), then over-
   engineering / organisation, then doc-vs-code drift.  Note which
   ones you fixed already vs which need operator approval.
4. **A concrete "if I were you, I'd do X next" recommendation**
   for the next 5-10 commits the operator should ship.  Operator's
   priority is "performance + organisation + reliability" — not
   new features.
5. **One brutally honest piece of feedback** about something
   that's wrong / over-engineered / structurally bad — even if it
   doesn't fit a numbered category.

Don't pad with "what's good" — focus on what to fix + what's next.

**Hard out-of-scope reminder** — see top of brief.  App/daemon
architecture changes need an explicit plan + operator approval
before any implementation.  Don't unilaterally refactor the
single-process model.

---

End of brief.  Branch is `0.5.0`; latest agent-relevant commit is
`4dd094d`.  Scope is `jaeger_os/agent/` only.  Have at it.
