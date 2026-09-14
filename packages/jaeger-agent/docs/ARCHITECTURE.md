# JaegerAgent — architecture

What this module is, how a turn actually runs, and the handful of design
decisions that make it behave differently from a generic tool-calling
loop. Every number here was measured against the source, not estimated;
where a design was tried and *failed*, that is recorded too, because a
refuted idea is the most expensive kind to re-discover.

Companion docs live beside this one:

| Area | Doc |
| --- | --- |
| One turn, end to end | [`pipelines/agent_turn_pipeline.md`](pipelines/agent_turn_pipeline.md) |
| Context window management | [`core/context_guard.md`](core/context_guard.md) |
| The public runtime contract | [`core/agent_contract.md`](core/agent_contract.md) |
| Dynamic tool surface (and why it is off) | [`core/toolset_scoping_ab.md`](core/toolset_scoping_ab.md) |
| Skill format and lifecycle | [`skills/skill_schema_v3.md`](skills/skill_schema_v3.md) |
| Station 3 / the voice pipeline | [`skills/agentic_runners.md`](skills/agentic_runners.md) |

> **Note on moved docs.** The files under `docs/core/`, `docs/pipelines/`
> and `docs/skills/` were written while this code still lived inside
> JaegerAI. They cite paths like `agent/loop/jaeger_agent.py` and
> `jaeger_os/main.py`. Read those as `jaeger_agent/loop/jaeger_agent.py`
> and "the host application" respectively. The reasoning is current; the
> paths are pre-extraction.

---

## 0. What belongs here at all

**Applications are where things are designed, developed and tested. Only
what is locked in gets a channel to the agent.**

That rule decides both code and documentation. An idea is prototyped in
JaegerAI or Mochi against a real instance, a real microphone, a real
user. It earns its way into this module only once its shape has stopped
moving — and what arrives is the *mechanism*, not the exploration that
produced it.

| Stays in the application | Merges into the module |
| --- | --- |
| Design explorations, mode A/B/C comparisons | The mode that shipped |
| Build plans, backlogs, roadmaps | The built thing |
| Product policy — which character, which voice | The seam that policy plugs into |
| Character formats, trait layers, safety policy — still being designed, differently, in each app | The *channel* a compiled character arrives through (§6) |
| Benchmark corpora under active authoring | Benchmark *results* that settled a decision |
| Anything still changing shape | Anything other apps must be able to rely on |

The practical test: **could a different application depend on this?** A
persona *mechanism* — yes, Mochi uses it. A persona *design document
comparing three unbuilt modes* — no, that is JaegerAI's R&D and belongs
with JaegerAI.

This is why the A/B benchmark results in `docs/core/` *are* here while
the design docs that proposed them are not. A refuted experiment is a
locked decision — the most valuable kind, because it stops the next
person re-running it. An unbuilt proposal is still R&D.

---

## 1. What it is

JaegerAgent is a JaegerOS `slot: mind` module — the only module kind that
*decides* rather than executes. It ships a complete agent, not a loop you
then have to furnish:

| | count | where |
| --- | ---: | --- |
| Tools registered at import | **97** | `jaeger_agent/tools/` |
| Named toolsets | **28** | `jaeger_agent/schemas/tool_bundles.py` |
| Playbook skills | **107** | `jaeger_agent/skills/` |
| Provider adapters | **6** | `jaeger_agent/adapters/` |
| Prompt dialects | **6** | `jaeger_agent/dialects/` |
| Tests | **418** | `tests/` |

Adapters: `anthropic`, `openai`, `local_llama`, `mlx`, `hermes_xml`, plus
the `base` protocol. Dialects: `chatml`, `gemma`, `harmony`, `llama3`,
`mistral`, and `detect` which picks among them.

A bare `pip install jaeger-agent` brings llama.cpp weights in-process — no
server, no API key, nothing leaving the machine. That posture is
deliberate and is why `llama-cpp-python` is a base dependency rather than
an extra.
---

## 1a. Named mechanisms — the index

Each distinctive mechanism has **one canonical name**. Use these names in
code comments, commit messages and issues; a mechanism referred to by
description instead of name is one nobody can search for. Names already
coined in the source are kept as-is rather than re-branded.

| Name | What it is | Lives in | § |
| --- | --- | --- | ---: |
| **The Soft Loop, Hard Boundary Runner** | The four-station turn architecture: a deliberately unconstrained interior with all the discipline at the exits | `loop/` | §2 |
| ├ **Station 1 — The Fluid Loop** | Research ⇄ execute in one context, pivots allowed, never denied mid-flow | `loop/jaeger_agent.py` | §2 |
| ├ **Station 2 — The Verify Gate** | Last-exit check on candidate final answers | `loop/verify_gate.py` | §2 |
| │  ├ **The Plan-Halt Check** | Catches a plan emitted where an answer belongs | `loop/verify_gate.py` | §2 |
| │  └ **The Claim-vs-Action Check** | Catches "I've saved it" with no successful mutating call that turn | `loop/verify_gate.py` | §2 |
| ├ **Station 3 — The Persona Pass** | One bounded clean-context call that restyles the final answer | `prompts/persona_filter.py` | §6 |
| └ **Station 4 — The Reflect Journal** | Post-turn journaling after non-trivial tasks | `prompts/reflection.py` | §2 |
| **The Loop Backstop** | Identical-call, semantic-failure and runaway detection inside Station 1 | `loop/jaeger_agent.py` | §2 |
| **The Skip-Final Fast Path** | One deterministic tool on iteration 1 answers without a second model call | `loop/jaeger_agent.py` | §2 |
| **The Declared Fragment Registry** | Every line reaching the model is a named, enumerable fragment — hidden conditional injection is structurally impossible | `prompts/assemble.py` | §6 |
| **The Split-Context Persona Pipeline** | *Name-in, voice-out*: identity name at the start, character only at the end, vanilla worker in between | `prompts/assemble.py` + `persona_filter.py` | §6 |
| **The Character Block Channel** | The opaque `character_block` string — the one seam an app pours its character through | `prompts/persona_filter.py` | §6 |
| **The Host Contribution Path** | A host's tools, toolsets and skills are equal to the module's | `skill_registry/toolset_scoping.py` | §3 |
| **The Self-Check** | 19 model-free assertions on the surface — `python3 -m jaeger_agent selfcheck` | `core/selfcheck.py` | §9 |
| **The Boundary Ratchet** | App-import budget that can only fall | `tests/test_module_boundary.py` | §7 |
| **Persona Mode C — The Id/Ego Lane** | Optional lane where the character speaks first and reaches the agent through exactly one `perform_task` tool | `prompts/persona_lane.py` | §6 |
| **The Content Survival Gate** | Restyled never means replaced — facts, numbers, paths must survive verbatim | `prompts/persona_filter.py` | §6 |
| **The Staged Context Guard** | Four-stage degradation instead of a cliff | `util/context_guard.py` | §5 |
| ├ **Stage 1 — Result Pruning** | Stub oversized tool results once their turn leaves the protected tail | `util/context_guard.py` | §5 |
| ├ **Stage 2 — The Digest Fold** | Dropped turns become one merged reference message | `util/context_guard.py` | §5 |
| ├ **Stage 3 — In-Flight Compaction** | The current turn overflowed alone; stub its oldest results | `util/context_guard.py` | §5 |
| └ **Stage 4 — Typed Refusal** | `ContextOverflow`, never a silent truncation | `util/context_guard.py` | §5 |
| **The Serving-Model Rescope** | `ctx_window` follows whichever model is answering this turn, not a global constant | `loop/runtime_bridge.py` | §5 |
| **The Completion Reserve** | Answer room held back, clamped to half the window | `loop/runtime_bridge.py` | §5 |
| **Toolset Scoping** | On-demand tool surface — **built, benchmarked, refuted, kept off** | `skill_registry/toolset_scoping.py` | §3 |
| **The Playbook Skill Corpus** | 107 `SKILL.md` recipes loaded on demand via `use_skill` | `skills/` | §4 |
| **The Skill Enum Gate** | `use_skill`'s `name` is a generated enum, so a skill that does not exist cannot be named | `tools/skills.py` | §4 |
| **The Live Tool Registry Read** | The registry is re-read every turn, so anything that registers becomes reachable without this package knowing it exists | `loop/jaeger_agent.py` | §3 |
| **The Layout Bind Seam** | `workspace.bind(layout)` — host-injected instance root for all tool I/O | `core/workspace.py` | §7 |

---

## 2. The turn pipeline — The Soft Loop, Hard Boundary Runner

One user message becomes one reply through `format → call → parse →
dispatch`, looping up to `max_iterations` (24).

```
ChatMessage (/act/chat) or Transcript (/sense/stt/transcript)
      │  AgentBridge._on_chat / _on_transcript → inbox queue
      │  (turn already live? steer() it instead of queueing)
      ▼
AgentBridge._loop  (worker thread)          jaeger_agent/core/bridge.py
  publish AgentState "thinking"  → /sense/agent_state
      │
  drive_one_turn(agent, text)               loop/runtime_bridge.py
      ▼
  JaegerAgent.run_turn(user_message)        loop/jaeger_agent.py
    append {role:"user"}, then loop:
      │
  ┌─▶ 1  pre-flight ContextGuard trim  (§5)
  │   2  format_messages → adapter.call → parse_response
  │      (classified retry + fallback chain; heartbeat ticks)
  │   3  append assistant Message (may carry text AND tool_calls)
  │      no tool_calls → return text ───── final answer ──▶
  │   4  The Skip-Final Fast Path: iteration 1, one deterministic tool,
  │      non-multistep → dispatch + finalize, no second model call
  │   5  dispatch each tool_call → append {role:"tool"}
  │      (all-read / path-scoped batches run via _dispatch_parallel)
  │      The Loop Backstop: identical-call · semantic-failure · runaway
  └────── loop ◀───────────────────────────────────────────┘
      │
  ChatReply → /sense/chat ; AgentState "idle"
```

### The four stations

The loop above is Station 1 of a four-station runner — *"soft loop, hard
boundary"*, one model context, zero added latency on the happy path:

| | | |
| --- | --- | --- |
| **Station 1 — The Fluid Loop** | research ⇄ execute, pivots allowed | benched E4B 77-78/81 — *do not touch* |
| **Station 2 — The Verify Gate** | `loop/verify_gate.py`, at the single `if not tool_calls:` exit | one nudge max, never denies |
| **Station 3 — The Persona Pass** | `prompts/persona_filter.py` | §6 |
| **Station 4 — The Reflect Journal** | post-turn journaling | feeds future skill creation |

**Station 2** runs only on a candidate *final* answer, so a clean answer
costs nothing. It catches two failure shapes. **The Plan-Halt Check** (the text is a
plan, not an answer — the model narrated and ran out of steam) and **The
Claim-vs-Action Check** (the text claims a completed mutation in first person
— "I've saved/scheduled/remembered…" — with no matching successful tool
call that turn; the runner already tracks per-turn successes for free).

Its guarantees come from a specific failure — an earlier hard gate took
the bench from **73 to 66**. So: at most **one** nudge per turn, the nudge
is synthetic and never persists in session history, and the gate **never
denies** — if the model still won't act, its answer is accepted. A failed
nudge is information, not a wall. Kill switch `JAEGER_VERIFY_GATE=0`.

`run_turn` repairs the transcript on **every** exit path. A pre-flight
overflow rolls the user message back and re-raises; a mid-turn overflow,
interrupt, or error closes dangling tool calls so the next turn still
formats cleanly. A half-open tool call is how a transcript becomes
permanently unusable, and no provider forgives it.

**Bus contract.** Consumes `/act/chat`, `/sense/stt/transcript`,
`/act/response`. Produces `/sense/chat`, `/sense/agent_state`,
`/sense/tool`, `/sense/activity`, `/sense/request`. Note what is *absent*:
the mind never publishes `/act/speech/say`. It has no opinion about being
heard — see §7.

---

## 3. Tools — The Live Tool Registry Read, and why Toolset Scoping is off

97 tools register themselves at import time onto the process-wide
JaegerOS registry. The agent re-reads that registry every turn, which is
why any module, skill, or MCP server that registers a tool becomes
reachable without this package knowing it exists. That is also why
`module.yaml` declares `tools: []` — the mind calls tools, it does not
contribute them.

### Toolset Scoping — built, benchmarked, refuted, kept

The obvious optimisation: don't show a small model ~96 schemas. Keep a
~17-tool CORE visible and let the model pull the rest on demand via a
`load_toolset` tool. Each skill is its own self-describing toolset.

It was built, and benchmarked — 33 prompts, Gemma 4 26B-A4B, in-process:

| | All tools visible | Toolset scoping |
| --- | ---: | ---: |
| Routing accuracy | **28/33 (85%)** | 22/33 (67%) |
| Avg per prompt | **2.83s** | 3.16s |

**Scoping cost 18 points of accuracy and was slower.** The `load_toolset`
meta-step is the culprit: the model must first *realise* it needs a
toolset, *call* the loader with the right name, then call the real tool.
Gemma 4 does not reliably take that step — it answers in plain text or
grabs a wrong core tool instead.

The deeper finding is the one worth keeping: **"too many tools" was never
the routing bottleneck.** A 26B model handles a 96-tool surface at 85%.
Adding the meta-step *created* failures that did not previously exist.

So the machinery ships **off**: `JAEGER_TOOLSET_SCOPING`, default `0`. The
code is deliberately kept, because it is the foundation for the one
variant that might still win — *auto-load on intent*, where a cheap
keyword pre-pass loads the likely toolset **before** the turn so the model
never takes the meta-step at all.

This is the house discipline, and it recurs: build it, benchmark it, and
if it is not a win, **flag it off rather than ship it**. The same
happened to the native chat handler ([`core/native_handler_ab.md`](core/native_handler_ab.md)).

### Permission tiers

Every tool declares a `side_effect`. Write-tier tools are gated, and the
gates fail *closed* — a tool whose owning module is absent reports
unavailable rather than falling through to an optimistic default. That
fail-open regression happened once, in the plugin era, and the current
`_TOOL_TO_MODULE` / `_TOOL_TO_SLOT` split in `core/availability.py` exists to
prevent its return.

---

## 4. Skills — The Playbook Skill Corpus and The Skill Enum Gate

A skill is a `SKILL.md` playbook the agent reads **on demand**. 107 ship
in the box. They are not prompts and not tools; they are recipes that
tell the model *how to sequence the tools it already has*.

The mechanism is one tool, `use_skill(name)`, whose description is the
whole design:

> *"Load a specialized JROS playbook recipe and FOLLOW it. Call this
> BEFORE raw tools for any specialized task — first scan your skills for
> a match; only if NONE fits do you reach for raw tools."*

`name` is a generated enum of the available skills, so the model cannot
hallucinate a skill that does not exist — the schema constrains it.

**Why this raises agentic quality.** A generic loop, asked to "analyse
this codebase," improvises an order of operations every time and
improvises differently every time. A skill fixes the sequence that was
found to work, so the model spends its reasoning on the *problem* rather
than re-deriving procedure. It is progressive disclosure applied to
method rather than data: the catalogue is cheap (names only), the recipe
is loaded only when chosen.

Note the asymmetry with §3. Loading a *skill* on demand works; loading a
*toolset* on demand did not. The difference is that choosing a skill is
the task the model is already doing — deciding what kind of problem this
is — whereas choosing a toolset is bookkeeping the model has no reason to
care about.

Skills are also the self-improvement seam: `reload_skills()` re-scans
after the agent authors a new one. See
[`pipelines/skill_discovery_pipeline.md`](pipelines/skill_discovery_pipeline.md)
and [`pipelines/skill_self_improvement_pipeline.md`](pipelines/skill_self_improvement_pipeline.md).

---

## 5. The Staged Context Guard

`util/context_guard.py`. Runs pre-flight on every turn, and degrades in
defined stages rather than failing at a cliff.

| Stage | Name | Action |
| --- | --- | --- |
| **1** | **Result Pruning** | Stub oversized tool-result bodies once their turn leaves the protected tail. The artifact path survives in the stub, so the model can read any of it back. |
| **2** | **The Digest Fold** | Fold dropped turns into one `[EARLIER CONTEXT — REFERENCE ONLY]` message — what was asked, what tools ran, what errored. A previous digest is *merged*, never stacked. |
| **3** | **In-Flight Compaction** | The current turn overflowed *by itself* (39 file reads, a big grep). Stub its **oldest** results, protecting the last two and the user message. |
| **4** | **Typed Refusal** | `ContextOverflow`, typed. |

**Stage 3 — In-Flight Compaction** is the newest and the one that changed a documented invariant.
Before it, "everything after the latest user message is verbatim" was
absolute, and a turn that read too much was simply lost with its work.
Now that guarantee holds *until stage 3*. The cost is real — the model
continues on stubs — so it is reported separately as
`TrimResult.inflight_pruned_count` rather than folded into the ordinary
prune count, and the turn surfaces it on `on_thinking`.

Two budget subtleties worth knowing:

- **The Serving-Model Rescope.** `ctx_window` means the *serving* model's window, not a global
  constant. A cloud model answering and the local worker lane have
  different windows; the guard is rescoped per active model per turn.
- **The Completion Reserve** (`completion_reserve`) is held back from the prompt budget because the
  server counts prompt + completion against **one** window. A reserve
  smaller than the answer you asked for overflows at generation time even
  though the prompt fit. It is clamped to half the window so a
  misconfigured `max_tokens` cannot zero the prompt budget.

---

## 6. The Split-Context Persona Pipeline — name-in, voice-out

This is the module's most distinctive decision, and the easiest to
mistake for ordinary persona prompting. It is the opposite of that.

**The measured problem.** A character in the execution context costs a 4B
model **~7 bench points**. Personality tokens sitting beside tool schemas
and history degrade routing — the model spends attention being someone
while it is trying to decide something.

**The answer: the model thinks in a standard, non-persona frame, and
persona is applied at exactly two touchpoints — one line at the start,
one bounded call at the end.**

```
   ┌── START ────────┐   ┌── MIDDLE ──────────┐   ┌── END ──────────────┐
   │ identity NAME   │   │  STATIONS 1-2      │   │ STATION 3           │
   │ one line, from  │──▶│  the fluid loop +  │──▶│ apply_persona_voice │──▶ user
   │ identity.yaml.  │   │  verify gate.      │   │ answer + character  │
   │ A FACT, not a   │   │  NO character.     │   │ block. No tools,    │
   │ persona.        │   │  Workers vanilla.  │   │ history or schemas. │
   └─────────────────┘   └────────────────────┘   └─────────────────────┘
```

**Why the name — and only the name — goes in at the start.** A wrong name
cannot be repaired downstream, because Station 3 preserves facts
verbatim: if the worker calls itself the wrong thing, the filter
faithfully keeps the wrong thing. So `identity_name` is one line, always
`identity.yaml`'s `name`.

**Identity is not character**, and that separation is an explicit operator
decision: the character *never* supplies the agent's name. The character
is the persona only — *"a robot like Jarvis, but I will name him Ted."*
Station 3's context then injects "your name is `<identity.name>`; you
embody `<character>`'s persona", so the rewrite keeps the instance name
while taking the character's voice.

**What happens if you break this**, measured 2026-07-05: with HAL 9000 as
the active character, the prompt `"a story about a robot"` wrote its story
about **HAL 9000** — deterministically, 2/2 versus 0/2 A/B on E4B. A
character name in the worker prompt tints free text and false-negatives
`answer_contains`. That is why the character name had to leave.

**The Declared Fragment Registry** is what makes this checkable.
`prompts/assemble.py` holds `PROMPT_FRAGMENTS`, and nothing reaches the
model that is not a named fragment in that list — so every rule the LLM
receives can be enumerated along with where it came from, and a hidden
conditional injection is structurally impossible. Line 116 says it
outright: *"there is deliberately
NO character/persona fragment here."* The registry of prompt fragments
has `safety`, `framework`, `instance` and `dynamic` kinds — and no
persona among them.

The single exception is the agent's **name**, and the reasoning is exact:
*a name is a fact, not a persona.* The fragment note reads "the agent's
NAME only (never the character's) — persona stays in the output filter."

### Why this influences results without harming them

Because the character is applied **after** the work is finished, in a
call that cannot see the work being done, it cannot bias tool selection,
planning, or recovery. The engine is *always* measured persona-off — the
bench drives the loop directly and never passes through Station 3, so
routing numbers are never flattered by voice and never damaged by it.

What the character still does is real: it decides how the answer sounds,
which for a conversational assistant is most of the perceived quality.
Same correctness, different product.

Guardrails, all deliberate:

- **Fail-open.** Any failure — model error, empty rewrite, oversized
  input — returns the **original answer untouched**. Losing voice is
  acceptable; losing the answer is not.
- **The Content Survival Gate.** `_preserves_content` gates the rewrite. Facts,
  numbers, units, paths, URLs and code must survive verbatim; restyled
  never means replaced.
- **Bounded.** Answers over `DEFAULT_MAX_CHARS` (1600) pass through
  unstyled — rewriting a long report risks mangling it and doubles
  latency exactly when the answer was already expensive.
- **Killable.** `persona.output_filter: false` in config, or
  `JAEGER_PERSONA_FILTER=0` in the environment.

### The Character Block Channel

```python
apply_persona_voice(answer, character_block=<app-compiled text>)
```

`character_block` is **opaque**. The module never parses it, never
validates it, and has no opinion about where it came from.

That matters because applications genuinely disagree here. JaegerAI
compiles a character from four trait layers (hexaco · special ·
expression · domains) plus identity and soul. Mochi uses a different
character structure entirely, and is still changing it. Both are R&D —
being designed and tested in different directions at the same time (§0).

Neither format reaches this module. Each application compiles its own
characters into a block and hands the string over. The agent owns the
*channel*; the apps own the *character*. That is why two applications
with incompatible character models can share one agent unchanged — and
why `tools/persona.py`, which reads JaegerAI's trait layers directly, is
six-for-six coupled to JaegerAI and should move back there (§7).

### Persona Mode C — The Id/Ego Lane (a separate mechanism)

Not to be confused with the above. Mode C (`prompts/persona_lane.py`) is
an **optional lane** in which the character speaks first and reaches the
clean agent through exactly one tool, `perform_task`.

The framing is Freudian and load-bearing rather than decorative: the
persona lane is the **id** (voice, desire, wants to answer now); the
clean agent is the **ego** (reality principle — a tool call *is*
reality-testing); the permission tiers, e-stop and fail-closed gates are
the **superego**, refusing regardless of what either wants.

The invariant that makes it safe: **the id never touches reality
directly.** Lilith cannot assert the time — she must delegate to the ego,
which checks. Every hallucination of that shape is a persona answering a
reality question it should have handed off.

It shares the property that makes §6 work — `perform_task` runs
persona-off with every tool and the hardened prompt — plus three of its
own:

1. **Delegation is a tool call, not a prose classifier**, so it inherits
   the reliability the routing bench already measures instead of
   inventing a new, unmeasured decision path.
2. **Recursion is structurally impossible, not policed.** The
   `perform_task` closure is built by the caller and invokes
   `drive_one_turn` directly — there is no code path back into the lane.
3. **Compose never means replace** — it reuses Station 3's content
   survival gate, imported rather than duplicated.

`run_persona_turn` returns `None` **only** for a failure *before*
`perform_task` runs — the caller's signal to fall through to plain Mode A
untouched. Once `perform_task` has been called it always returns a
string, because the alternative is running the turn twice.

## 7. The module boundary — The Layout Bind Seam and what still leaks

`docs/EXTRACTION.md` states the rule plainly:

> **JaegerAgent depends on JaegerOS. JaegerAI depends on JaegerAgent.
> JaegerAgent must never import JaegerAI.**

Where the boundary holds:

- Neural input/output dependencies remain lazy and optional. The reusable
  multimodal engine owns its node runtimes; importing `jaeger_agent` does not
  import pyaec, Kokoro, or pywhispercpp.
- The instance layout is **injected**, not fetched: `workspace.bind(layout)`
  wires all tool I/O to a host-chosen directory at startup, and the
  `InstanceLayout` type import is `TYPE_CHECKING` only.
- The package's full suite and self-check run without booting a host
  application.

Remaining host-extension seams:

- Some optional product integrations still late-import JaegerAI when that host
  is installed: persona/plugin bridges, application telemetry, and a few
  desktop tools. They are not imported by package startup or the multimodal
  engine. Each remains listed in `core/host.py` until replaced by an injected
  host contribution or moved back to the application.
- Host-specific tools can therefore degrade when the corresponding host hook
  is absent. The core loop, local runtime, memory, standard tools, skills, and
  multimodal runner operate standalone.

**The direction of the fix is the interesting part.** Embedded in Mochi,
it is Mochi's character that applies, not JaegerAI's — so the agent cannot
name either. The pattern that works is inversion: the **app pushes into
the agent**, the agent never pulls. Mochi already does this
(`modules/jaeger_agent.py :: set_persona`), and JaegerAI adopted it in
`0.11.0`. Each remaining coupling wants the same treatment — a seam here,
filled by whichever application is hosting.

---

## 9. Verifying it

Two things, deliberately separate.

**The Self-Check** — `python3 -m jaeger_agent selfcheck [--json]`. 19
assertions, under a second, no model and no host. It catches what only
surfaces mid-turn: a schema that will not serialise, a duplicate or
wire-unsafe tool name, a toolset naming a tool nothing provides, a skill
offered but unloadable, a dialect that cannot render the catalogue, a
declared dependency that does not import.

That last one earned its place immediately. `croniter` backs cron
parsing, was never declared, and in an environment without it
`schedule_prompt` failed mid-turn — the agent diagnosed the missing
package and tried to `install_package` to repair itself. A benchmark
found that; a one-second check now does.

**The bench** answers a different question — *does the model route
well?* — and it needs a live model, an instance, and minutes. The corpus
lives here (`jaeger_agent/bench/`) because it measures this module; the
runner stays in the application because it needs a live agent and an
instance layout.

Between them sits **The Boundary Ratchet**
(`tests/test_module_boundary.py`), which fails when app imports rise AND
when they fall — a budget nobody edits is a budget that stops meaning
anything.

---

## 8. Reading order

New to the module: §2, then
[`pipelines/agent_turn_pipeline.md`](pipelines/agent_turn_pipeline.md).

Changing routing or tools: [`core/toolset_scoping_ab.md`](core/toolset_scoping_ab.md)
first — it will save you from re-running a refuted experiment.

Changing the context guard: [`core/context_guard.md`](core/context_guard.md),
and note the stage-3 invariant in §5.

Touching persona: §6 first, and note it describes **two different
things**. The dual context pipeline (execution vanilla, voice applied
after, `prompts/persona_filter.py`) is always on and is why a character
costs no accuracy. Persona Mode C (`prompts/persona_lane.py`) is an
optional lane on top of it; its module docstring is the authoritative
statement of that contract.

Before adding anything character-shaped to the system prompt, read
`prompts/assemble.py` line 116 and the ~7-point measurement behind it.
The omission is the feature.

The R&D that produced both — the persona compiler, the A/B/C mode
comparison, the Mode C build plan — stayed in JaegerAI per §0. Read those
for *why*; read here for *what shipped* and *what other apps can rely
on*.
