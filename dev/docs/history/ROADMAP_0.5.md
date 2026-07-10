# JROS 0.5 Roadmap — Animation + Personality + Skill Tree + Streaming

**Status:** active (2026-06-08) — foundation scaffolded; iterating
**Branch:** `origin/0.5.0`
**Pre-req:** 0.4.0 shipped + tagged + merged to main (commit fc8eea1)
**Target:** the agent grows visibly — XP-driven skill tree, Mochi-vendored
animation node, Swift-native renderer, structured personality, streaming mode.

## The position

0.4 wired the spine (nodes, bus, voice).  0.5 makes it visibly alive
and continuously evolving.

> **An embodied, continuously-improving agent — animation +
> personality + skill tree.**
>
> The agent has a Mochi-style face rendered by a Mac-native Swift
> app.  It carries structured personality (HEXACO + expression
> sliders + domain weights) into every turn.  Every node + skill is
> a tree node — earns XP through use, levels up, unlocks more
> capable variants.  Multi-track timelines coordinate performances
> across animation + speech + sound + (future) motion + light.
> A streaming mode the operator points OBS at and calls a YouTube
> show.

The architecture decisions from 0.4 carry over verbatim:

* Brain stays one process; new capabilities are nodes.
* Tools = networking shims; nodes = execution.
* Universal interfaces in the library; per-instance specifics
  at the operator's instance dir.
* msgspec for transport schemas; Pydantic for config + manifest.
* Make it exist first, then make it good.

New operator-locked architectural principles (2026-06-08):

* **Conscious / unconscious model** (from 0.4) — peripheral nodes
  filter / gate / reflex so the brain only engages on confirmed
  signals.  See 0.4 CHANGELOG for the audio-side codification.
* **Skill-tree evolution** — every node + skill has progression
  levels.  XP accumulates from real use.  Skills unlock skills
  through prerequisites.  See `dev/docs/SKILL_TREE.md` for the
  load-bearing pattern, and
  [`dev/docs/0.5.x_skill_tree_evolution_plan.md`](0.5.x_skill_tree_evolution_plan.md)
  for the planned evolution from "registry + log" to
  "behaviour-shaping system" (prompt-feedback, behaviour-shaping,
  visualisation).
* **Animation levels** — L1 static → L2 sprite → L3 gif → L4 video
  + procedural → L5 rigged (deferred) → L6 generative (deferred).
  Each level is a skill node.

## The vendoring decisions

**Mochi → JROS animation node.** The operator's prior animation work
at `/Users/jonathanjenkins/GITHUB/Mochi/` is Apache 2.0 and ships
nearly the exact architecture we want.  The 7 handler types (image,
bitmap, sprite, gif, video, math, media) become the 0.5 adapter
implementations spanning L1-L4.  Mscript stays as a one-way
compiler input (existing `.mscript` files compile to Timeline at
load time); no new mscript is authored.  See
`dev/docs/library_review/mochi_demo.md` for the full audit +
vendoring map.

**Swift renderer at `apps/JROS-Avatar/`.** Mac-native rendering;
ships with the framework.  Python AnimationNode publishes pixel
buffers over WebSocket; the Swift app displays them.  Phased plan
in `dev/docs/0.5.0_swift_renderer_plan.md`; Phase 1 scaffold
(window + WebSocket + decoder) shipped 2026-06-08.

**Open-LLM-VTuber → reference only.** The earlier plan was to
vendor their Live2D pipeline.  Operator pivoted to Mochi-style
faces (simpler, robot/companion identity, no Live2D licence
complexity).  Open-LLM-VTuber stays as architectural reference for
WebSocket-driven avatar patterns.  Live2D becomes L5 — a deferred
adapter slot, not the foundation.

## Foundation scaffolded 2026-06-08 (already on the branch)

| Component | Where | What |
|---|---|---|
| Skill-tree pattern | `dev/docs/SKILL_TREE.md` | XP-driven progression contract — every node + skill obeys this |
| Skill-tree runtime | `jaeger_os/skill_tree/` | msgspec schemas + registry + atomic persistence + listener API |
| Skill-tree XP wiring | `jaeger_os/skill_tree/xp_emitter.py` | Bus subscriber that applies `XpAwarded` events to the registry + mirrors state events back onto the bus |
| Default catalog | `jaeger_os/skill_tree/seed.py` | Pre-populated skill graph: animation L1-L6 + voice + vision + motor + light + core tools |
| New bus topics | `jaeger_os/topics.py` | `AnimationCommand`, `AnimationStop`, `AnimationState`, `TimelineCommand`, `TimelineProgress`, `XpAwarded`, `SkillLevelUp`, `SkillUnlocked`, `SkillMastered` |
| Mochi audit | `dev/docs/library_review/mochi_demo.md` | Vendoring map for 7 handler types + L1-L4 mapping |
| AnimationNode | `jaeger_os/nodes/animation/` | Node + adapter Protocol + frame callback seam to renderer |
| Animation adapters L1-L4 | `jaeger_os/nodes/animation/adapters/` | image / bitmap / sprite / gif / math — vendored from Mochi |
| FrameBridge | `jaeger_os/nodes/animation/bridge.py` | WebSocket server ships frames to the Swift app + any browser-source client |
| Timeline schema | `jaeger_os/timeline/schema.py` + `dev/docs/0.5.0_timeline_schema.md` | OTIO-inspired multi-track JSON; mscript-compile path defined |
| Timeline runner | `jaeger_os/timeline/runner.py` | Wall-clock multi-track dispatcher; per-track bus publishing; interrupt-clean |
| Personality module | `jaeger_os/personality/` | HEXACO + SPECIAL + Expression + Domains + speech patterns; `compose_block` produces system-prompt language; wired into `assemble_prompt` |
| Swift renderer | `apps/JROS-Avatar/` + `dev/docs/0.5.0_swift_renderer_plan.md` | SwiftPM scaffold: window + WebSocket + FrameDecoder + 4 XCTests |
| Tests | `dev/tests/jaeger_os/{skill_tree,timeline,personality}/` + `dev/tests/jaeger_os/nodes/test_{animation,image_adapter,bitmap_adapter,sprite_adapter,gif_adapter,math_adapter,frame_bridge,animation_e2e}.py` | **+116 new Python tests + 4 Swift tests; total 2000+ passing** |

## End-to-end milestones reached

* **Animation pipeline proven end-to-end** (commit `db20e6e`).  Real
  AnimationCommand on the bus → ImageAdapter renders frame →
  FrameBridge ships over WebSocket → byte-perfect arrival at a real
  WebSocket client.  XP awarded.
* **Multi-track performances dispatchable** (commit `513deeb`).  A
  Timeline JSON drives TimelineRunner; per-clip events fire at
  their `t_offset_ms` on the right bus topics.
* **Personality affects every brain turn** (commit `09bb04a`).  An
  instance with `<instance>/personality.json` gets a structured
  HEXACO + Expression block appended to its system prompt.

What we write ourselves:

* The AvatarNode (Python; must satisfy JROS bus contract).
* The `/act/avatar_state` topic schema (msgspec.Struct, our SSOT).
* The WebSocket server (lightweight Flask/aiohttp; our tests).
* Integration with `/sense/spoken`, `/sense/transcript`, the agent's
  tool surface.
* Persona-to-avatar mapping (HEXACO + expression sliders →
  default expressions for the model).

Same pattern as `dev/tools/audio_smoke/voice_assistant_persistent.py`
— we vendored the operator's earlier voice loop as a working
reference, modified it freely, kept attribution in the file.

---

## Architecture additions

### New topic — `/act/avatar_state`

```python
class AvatarState(TopicMessage):
    """Brain → avatar node: set the avatar's emotional + spatial
    state.  Published by the agent (via a new `set_avatar_state`
    tool) AND automatically by the voice loop on state transitions
    ('listening' when STT opens, 'thinking' during agent decode,
    'speaking' when TTS fires)."""
    topic: Literal["/act/avatar_state"] = ACT_AVATAR_STATE
    emotion: str = "neutral"
    # "neutral" | "happy" | "sad" | "focused" |
    # "thinking" | "surprised" | "speaking" | "listening"
    look_at_x: float = 0.0      # -1.0 (left) … 1.0 (right)
    look_at_y: float = 0.0      # -1.0 (down) … 1.0 (up)
    blink: bool | None = None   # None = automatic; True/False = forced
    duration_ms: int = 0        # 0 = hold until next message
```

The agent's tool surface gains:

```python
set_avatar_state(emotion: str = "neutral",
                 look_at_x: float = 0.0,
                 look_at_y: float = 0.0)
```

Same "tool publishes, node executes" contract as
`text_to_speech` post-0.4.

### Identity schema promoted from free-text to structured

`config.identity.personality` (a single 2048-char free-text field
today) gains a structured sibling `config.identity.personality_v2`:

```yaml
identity:
  display_name: "Lilith"
  voice_id: "af_heart"

  personality_v2:
    schema: persona/v2
    hexaco:
      openness: 0.50
      conscientiousness: 0.50
      extraversion: 0.40
      agreeableness: 0.50
      neuroticism: 0.55
      honesty_humility: 0.85
    expression:
      sarcasm: 0.45
      warmth: 0.50
      verbosity: 0.50
      formality: 0.50
      directness: 0.80
      humor: 0.30
      empathy: 0.40
      aggression: 0.30
    domains:
      science: 0.85
      philosophy: 0.75
      technology: 0.90
    speech_patterns:
      - "Speaks with quiet precision — never wastes words"
      - "Asks incisive questions rather than making assumptions"
      - "Does not soften hard truths but delivers them without cruelty"
```

The composed system prompt block adds (when `personality_v2` is set):

```
## How I express myself (calibrated)

  Sarcasm:     low-medium       Warmth:    medium
  Directness:  HIGH             Formality: medium
  Verbosity:   medium           Humor:     low

## Speech patterns

  - Speaks with quiet precision — never wastes words.
  - …
```

Backward-compat: instances with only the v1 free-text field continue
to work unchanged.

---

## Tracks

### Track A — Foundations (audits + 0.5.0 prep)

Lock the design decisions before writing code.

* **A.1** `dev/docs/library_review/open_llm_vtuber.md` —
  audit of their structure.  What we'd vendor (Live2D loader,
  lip-sync, idle animations), what we wouldn't (their LLM/STT/TTS
  stack), licence notes (Open-LLM-VTuber MIT; Live2D Cubism SDK
  per-model + commercial-use distinctions), specific files to copy.
* **A.2** `dev/docs/library_review/lilith_personality.md` —
  audit of `/Users/jonathanjenkins/GITHUB/Lilith-AI/archive/`.  Maps
  every personality field Lilith 0.2.2 had to what JROS would do
  with it (system prompt composition, avatar default expressions,
  voice tuning, skill bundle hints).
* **A.3** First-class Lilith preset at `jaeger_os/personas/lilith.yaml`
  alongside `jarvis.yaml`.  Uses the v2 structured personality.
  No code path yet uses v2 — just the data is there.

### Track B — Personality (the soul)

Promote personality from one free-text field to a structured model
the agent actually USES on every turn.

* **B.1** `Persona` schema (Pydantic, in
  `core/instance/schemas.py`).  HEXACO + expression + domains +
  speech_patterns.  Optional field on `Identity`.
* **B.2** `core/prompts/persona_compose.py` — turns the structured
  data into a system-prompt block.  Pure function, unit-tested.
* **B.3** Compose into the system prompt every turn (the existing
  `assemble_prompt` flow gains a conditional block).
* **B.4** Wizard prefill — when an operator picks a preset that
  has `personality_v2`, the wizard writes it.  v1 free-text path
  continues to work for legacy instances.
* **B.5** Persona-driven voice tuning — high `humor` could nudge
  Kokoro toward a more playful voice; high `formality` toward a
  measured one.  (Stretch — only if Kokoro's parameter space
  supports it.)

### Track C — Avatar node (the face)

The Live2D-driven avatar.  Same per-subsystem package shape as
`jaeger_os/nodes/{tts,stt,vision}/`.

* **C.1** `jaeger_os/nodes/avatar/` skeleton.  AvatarAdapter
  Protocol + AvatarNode skeleton with no rendering, just lifecycle
  + subscriptions.  Tests with a mock adapter.
* **C.2** `WebRendererAdapter` — Flask + WebSocket server that
  serves a placeholder HTML page (no Live2D yet, just a visible
  test rectangle).  `./launch --stream` opens the page.
* **C.3** Vendor Live2D rendering pipeline from Open-LLM-VTuber.
  Copy specific files into `jaeger_os/nodes/avatar/web/` with
  attribution.  Replace their model-loader hooks with our
  WebSocket protocol.
* **C.4** Lip sync — `/sense/spoken` events drive mouth
  parameters.  Use Open-LLM-VTuber's amplitude-to-mouth-shape
  algorithm as the reference, port to our event flow.
* **C.5** Expression mapping — `/act/avatar_state.emotion` →
  Cubism expression file.  Start with 5 emotions: neutral, happy,
  sad, focused, thinking.
* **C.6** Idle animations — breathing, blinking, micro-movements
  so the model doesn't feel static.  Vendor from Open-LLM-VTuber.
* **C.7** `set_avatar_state` agent tool.  Publishes
  `/act/avatar_state`; respects permission tier.
* **C.8** Voice-loop auto-publishes — `/act/avatar_state` switches
  to "listening" when STT opens follow-up, "thinking" during agent
  decode, "speaking" while TTS plays.  Same node-shape: voice loop
  is a tool publishing, avatar node executes.

### Track D — Streaming mode

The OBS-capturable production surface.

* **D.1** `./launch --stream` boot mode.  Voice auto-on; avatar
  window auto-launched; TUI minimised (background mode); status
  bar shows on-air indicator.
* **D.2** Stream-specific config block in instance config:

  ```yaml
  stream:
    enabled: false
    avatar_window_url: "http://127.0.0.1:8765"
    show_stt_overlay: false   # for debugging
    show_thinking_indicator: true
  ```
* **D.3** Avatar HTML page becomes OBS-friendly — transparent
  background; fixed window size operator can pick (default
  1280×720).
* **D.4** Stream watchdog — if the avatar window crashes (rare
  but possible during browser GC), the node restarts it.  Same
  pattern Track D's supervisor-port from 0.4 followups will use.

### Track E — Hardware avatar (long-term, deferred to 0.5.x)

The avatar that runs ON the robot's screen, not just OBS.

* **E.1** Reuse the same `AvatarNode` + WebSocket protocol; the
  renderer just runs on a Jetson with an attached display.
* **E.2** Camera-driven eye tracking — vision node observes user,
  publishes `/sense/user_position`; avatar's `look_at_x/y`
  follows.

This is post-0.5.0; mentioned here so the architecture in Tracks
B + C doesn't paint itself into a corner.

**Operator-locked (2026-06-07):** each robot is a standalone
agent with ONE persona.  We deliberately don't design for
multi-persona switching within a single robot — Lilith's robot
is Lilith.  Jarvis's robot is Jarvis.  This keeps the avatar /
persona / voice / skill tuning cohesive per instance and avoids
the complexity tax of persona-swap UX.

### Track G — Audio control topics + brain pre-LLM gate

Deferred from the 0.4 audio refactor request
([`0.4.0_audio_refactor_prompt.md`](0.4.0_audio_refactor_prompt.md)
Steps 5-6).  These were originally proposed by the reviewing
agent as 0.4.0 hardening; operator scoped them to 0.5 because
each adds new SSOT entries or new architectural layers that
deserve their own deliberation pass.

* **G.1** Audio control topics:
  - `/control/mic_pause`
  - `/control/stt_followup_open`
  - `/control/audio_drain_pending`
  - optional `/control/audio_mode`

  Replaces the direct `stt.set_paused()` / `stt.open_followup()`
  / `stt.drain_pending()` method calls the voice loop +
  AudioSessionNode still use today.  Bus-managed lifecycle
  matches the rest of the node fleet.

* **G.2** Pre-LLM voice gate inside the AudioSessionNode or
  voice orchestrator path.  Cheap deterministic filters BEFORE
  the LLM gate sees the phrase:
  1. Empty / junk marker gate
  2. Minimum content gate
  3. Repeated transcript gate
  4. Stale phrase gate
  5. Busy-turn coalescing (5 fragments while agent is busy →
     one next-turn batch, or dropped as stale)
  6. Optional small intent classifier (deferred sub-track)

  Rationale: don't spend Gemma 12B cycles on `[BLANK_AUDIO]` or
  on repeated identical transcripts.  The existing
  `<ignore>`/`<reply>` LLM gate stays as the SEMANTIC backstop
  for "was that addressed to me?"; this gate is the SYNTACTIC
  one for "is this real content?"

* **G.3** Tests + bench measuring gate hit rate against a
  collected voice log corpus.

### Track H — Turn routing classes

Deferred from the 0.4 audio refactor request Step 7.  A major
brain-loop change — voice should not route every accepted
phrase into the same slow path.

* **H.1** Route classification at the entry to `run_for_voice`:
  - `immediate` — short factual answer, local status, simple
    memory lookup, simple web/search with freshness
  - `clarify` — ask one follow-up question quickly
  - `background` — coding, research, code review, long
    benchmark, large tool workflow
  - `hardware` — robot body command, safety-gated

* **H.2** Rule-based router first (tool-intent heuristics).
  Promote to a small model only if the rule baseline plateaus.

* **H.3** Background work integrates with the deep-think
  kanban from 0.3 — a "background" route hands the task off,
  acknowledges via voice, and the agent stays responsive.

* **H.4** Tests + per-route latency budgets.

### Track I — Context staging + compaction

Deferred from the 0.4 audio refactor request Step 8.  Touches
every prompt path; deserves its own track.

* **I.1** Context levels:
  - `voice_minimal` — identity, active conversation summary,
    realtime commands, small toolset
  - `default` — current normal agent context
  - `deep_task` — coding/research skill docs, long memory,
    larger toolset, background board integration

* **I.2** `assemble_prompt` gains a `level` parameter; per-turn
  route classifier (Track H) picks the level.

* **I.3** Completed background work summarises back into memory
  instead of bloating the active voice prompt.

* **I.4** Bench cases measuring prompt size + decode latency
  per level.

### Track F — Node supervision + runtime (early in 0.5)

Operator-locked 2026-06-07: **bake the supervision framework in
NOW while we have ~6 nodes, not later when we have 20.**  Every
new node that lands AFTER this track inherits the pattern for
free; retrofitting it across a fleet is painful.

Previously deferred as Track D in the 0.4 roadmap.  Promoting to
a 0.5 Track because the cost-of-delay is real: avatar (Track C)
and persona hot-reload (Track B) both need supervision to be safe
on a live YouTube stream.

* **F.1** `dev/docs/library_review/mochi_demo.md` audit (with the
  Mochi reference 2026-06-08) explicitly catalogues supervision /
  runtime / health patterns Mochi already has — operator believes
  it does.  Anything reusable informs F.3.  Hermes's
  `supervisor.py` is also preserved at
  `dev/docs/library_review/hermes_supervisor.py` as a fallback
  reference if Mochi doesn't cover the supervisor piece.

* **F.2** New topic `/sense/health` + `NodeHealth` schema (msgspec.
  Struct).  Every node publishes a heartbeat each tick.  Schema:

  ```python
  class NodeHealth(TopicMessage):
      topic: Literal["/sense/health"] = SENSE_HEALTH
      node: str = ""
      state: str = "running"        # NodeState.value
      uptime_s: float = 0.0
      last_error: str | None = None
      extras: dict = msgspec.field(default_factory=dict)
  ```

  `Node.health()` already returns this shape; we just need the
  bus publish + a subscriber on the brain side.

* **F.3** `jaeger_os/supervisor.py` — port from the Hermes
  reference (or vendor patterns from Mochi if it has them),
  adapted for the Node base class.  Wraps a node thread /
  subprocess with:
  - exponential backoff on crash (doubles per crash, caps at 60s)
  - good-run reset (back to base delay after a long clean run)
  - crash log appended to `<instance>/run/supervisor.crash.log`
  - max-restarts gate (default unbounded; configurable)

* **F.4** Promote `runtime.ensure_*_node` factories from the 0.4
  patch round (`146b960`) to the canonical node-spawn path.
  Supervisor wraps the factory.  Operator never starts a raw
  node; they get a supervised one.

* **F.5** `/sense/health` subscription in the brain.  Surface
  missing heartbeats as "node X went dark":
  - `./launch --health` already exists; extend it with live
    node status
  - new `/nodes` TUI slash command lists active nodes + state +
    last seen
  - operator notifications when a node restarts (TUI status bar
    indicator)

* **F.6** Backpressure policy per-topic.  ZMQ HWM + InProcBus
  overflow path already exist; this track documents per-topic
  defaults:
  - audio frames: drop oldest (latency over completeness)
  - motor commands: drop oldest (most recent intent wins)
  - LLM tool dispatches: never drop (queue without limit)
  - health heartbeats: drop newest (one missed beat OK)

**Why F is early-0.5, not 0.5.x:**

1. Track C (avatar) ships in 0.5 → without supervision a renderer
   crash silently breaks the YouTube stream.
2. Track B (per-turn persona composition) ships in 0.5 → a
   compose bug becomes a per-turn crash; supervisor + health
   makes that recoverable instead of catastrophic.
3. Mochi-style face needs ~50 Hz lip-sync events on
   `/sense/tts_chunk` → backpressure policy matters; without
   it, a slow renderer wedges the bus.

Estimated scope: ~400 lines new code, ~150 lines tests.  Smaller
than Track B + C combined; big leverage.

---

## Milestones

### 0.5.0 — must-have

* Track A.1 + A.2 + A.3 (audits + Lilith preset data)
* **Track F.1 + F.2 + F.3 + F.4 + F.5 — node supervision +
  runtime framework lands EARLY in 0.5 before Tracks B + C add
  more nodes / per-turn complexity.**  Audit Mochi for existing
  patterns first; build on what's there.
* Track B.1 + B.2 + B.3 (structured personality affects the system
  prompt every turn)
* Track C.1 + C.2 + C.3 + C.4 + C.5 + C.6 + C.7 (avatar visible
  + breathes + lip-syncs + responds to `set_avatar_state`)
* Track C.8 (voice loop drives avatar state)
* Track D.1 + D.3 (`./launch --stream` opens the avatar window;
  OBS-friendly)
* Lilith persona working: HEXACO + expression composed into her
  system prompt; Live2D model showing on screen with her base
  expression; lip syncs when she speaks; agent can call
  `set_avatar_state("focused")` and the model responds.

**Verification gate:** point OBS at the avatar window, start
voice mode, have a conversation.  The avatar moves its mouth in
time with replies and changes expression when the agent calls
`set_avatar_state`.

### 0.5.1 → 0.5.4 — followups (deferred)

* B.4 wizard prefill for v2 personas
* B.5 persona-driven voice tuning
* C.x polish (more expressions, smoother lip sync, better idle)
* D.2 stream config block, D.4 stream watchdog
* Live YouTube chat → agent bridge (a new node: `youtube_chat`
  subscribes to chat events, publishes as if STT had transcribed
  them).  Optional but high-value once the rest works.
* E.1 → E.3 hardware avatar (Jetson display)

---

## Open questions

1. **Live2D model for Lilith.**  Community model for MVP
   validation, or commission/build one before 0.5.0 ships?
   Affects Track A.1 licence audit.

2. **Browser window vs. pywebview.**  For `./launch --stream`,
   should the avatar window be a real native window JROS owns
   (pywebview), or just a URL operators point their own browser
   at?  Native window feels more product-y; URL is simpler.

3. **Persona v1 → v2 migration.**  When does v1 free-text get
   deprecated?  Probably never — keep both forever, v1 is
   simpler for operators who just want "concise + helpful".
   But the wizard's default at 0.6+ should be v2.

4. **`set_avatar_state` permission tier.**  Pure UI control, no
   external effect.  Probably READ_LOCAL.  But could surprise
   an operator if the agent flips expressions during serious
   debugging.  Worth a `display.avatar_agent_control: bool` flag.

5. **Lip sync data source.**  `/sense/spoken` is the ack AFTER
   audio plays — too late for lip sync.  We probably need
   `/act/audio_out` (raw speaker frames) for amplitude analysis,
   OR a new `/sense/tts_chunk` published by the TTS node as
   each chunk fires.  The latter is cleaner.

---

## Library inventory queue

| Library | Status |
|---|---|
| **Open-LLM-VTuber** | A.1 audit pending — vendor working pipelines |
| **Lilith-AI archive** | A.2 audit pending — promote personality data |
| **Live2D Cubism Web SDK** | dependency for the renderer; licence audit during A.1 |
| **VoiceLLM** | absorbed at 0.4; operator may delete now |
| **Hermes** | absorbed at 0.4; supervisor preserved; operator may delete now |
| **JP01_Firmware** | informed Track C universal interfaces at 0.4; stays as reference for Track E hardware avatar |

---

## Position statement update (for `README.md`)

The 0.4 README pitch was:

> JROS = ROS + Agentic AI + Mac-first local hardware.

0.5 extends this without replacing it:

> **An agentic AI you can stream.**
> Local Gemma brain.  Live2D avatar.  Structured personality the
> agent USES every turn.  Voice-mode that feels like a
> conversation, not a chat box.  OBS-capturable out of the box.

The "stream" framing fits the YouTube channel goal without
abandoning the embodied-robot future — same code, same avatar,
just different output devices.
