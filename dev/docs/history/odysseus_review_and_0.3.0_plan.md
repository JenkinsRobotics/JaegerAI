# Odysseus review + 0.3.0 game plan

> Source reviewed: <https://pewdiepie-archdaemon.github.io/odysseus/> (the
> "archdaemon" branding belongs to PewDiePie's project, not to us).
>
> Caveat from the operator: **don't take Odysseus as gospel — it's a
> demo-grade single-author project, nowhere near the production bar
> Hermes (our original reference) hit.** Treat this as a brainstorming
> input, not a spec to copy. We mine ideas, not architecture.

---

## 1. What Odysseus actually is

A web-first local AI workspace. Single-author project. The landing
positions it as "all local, all open source, all yours" — same
local-first ethos as JROS but the surface is entirely a web app, not
embodied AI.

### Surfaces it ships

| Surface | What it does | JROS equivalent today |
|---|---|---|
| **Cookbook** | Catalog of ~270 "recipes" (model configs / system prompts / persona presets) the user can pick from | We have *one* persona per instance, baked into config + system prompt. No catalog. |
| **Deep Research** | Multi-step web research with progress UI + citation roll-up | We have `web_search` + `read_url` but no orchestrated "research run" surface. |
| **Email Assistant** | Reads/drafts email via local IMAP | We have iMessage / Discord / Telegram bridges. No email. |
| **Image Gallery** | Browse generated images, metadata-tagged | We have `generate_image` (SDXL local). No gallery / browse surface. |
| **Document Editor** | Markdown editor with agent assist inline | We have `edit_file` but no rich editor surface. |
| **Themes** | UI theming, light/dark/custom palettes | TUI has palettes; tray has none; no shared theme system. |

### Architecture footprint (what we can infer)

- **Web UI** as the only surface. Browser-hosted. Single-page app.
- **Local API** behind it (likely Ollama-style HTTP) — model swap by
  picking a recipe.
- **Per-feature mini-apps** within the same web shell.
- **No daemon/attach model** visible — looks like one process holding
  one model at a time. Recipes swap the model+prompt as a unit.
- **No agent loop visible in the materials** — feels closer to "tuned
  chat surface per use case" than tool-using agent. The "Deep Research"
  surface does multi-step retrieval, but it's not clear there's a
  general tool surface beyond what each surface internally calls.

### What it does well

1. **Catalog as front door.** The user opens the app and sees options,
   not a blank prompt. Picking a recipe = picking what the AI is *for*
   in this session. That framing lowers the cold-start barrier.
2. **One web surface, many uses.** A casual user doesn't context-switch
   between apps; one URL covers chat, research, writing, email, images.
3. **Polished landing page.** Bias toward the marketing surface as a
   first-class deliverable. We already moved on this with `docs/`.
4. **Theming as a feature, not a footnote.** Customization is part of
   the pitch, not an afterthought.

### What it doesn't do (the JROS edge)

1. **No embodiment story.** It's a chat surface. JROS aims at agents
   that drive real hardware — drones, humanoids, MCUs. Different game.
2. **No agent loop / tool surface in the agentic sense.** JROS has ~70
   tools across 11 toolsets, a real agent loop, MCP, kanban, deep think,
   self-authored skills. Odysseus is closer to a model-router with
   recipe-tuned UIs on top.
3. **No daemon / multi-client.** One model, one surface. JROS's
   daemon+attach lets voice + TUI + messaging + tray all share one
   model — that's the production-OS posture Odysseus doesn't have.
4. **No persistent memory beyond per-recipe history (apparent).** JROS
   has semantic + episodic memory baked in.
5. **No external messaging integration.** Email is internal-only. JROS
   already does Discord, Telegram, iMessage as bidirectional bridges.

**Net read:** Odysseus is a tuned *consumer* local-AI workspace.
JROS is an *agentic operating framework* for hardware. The closest
overlap is the "polished local-first chat surface" idea — we don't have
a web surface, they don't have an agent loop or hardware story.

---

## 2. Ideas worth stealing

Ranked by signal-to-effort, not raw ambition. Things that *don't* fit
the JROS thesis (embodied AI, agent OS) are explicitly listed below as
"skip" so we don't drift.

### A. Cookbook → "Persona Pack" catalog *(high signal, moderate effort)*

Odysseus's catalog is essentially: "pick the system prompt + model +
default-tools that match what you're doing today."

For JROS, that maps onto a **persona pack** — a portable bundle of:
- system prompt overlay (`personality.txt` style)
- recommended awake/asleep model pair
- starter skill set
- recommended toolset gating
- recommended permission posture

Then `./run.sh setup <name>` could offer "pick a starting pack" instead
of "fill out 6 wizard fields cold." The packs we ship by default:

- **Lilith — companion** (current default behavior)
- **Coder** — bias toward code skills, dev/benchmark, devstral
- **Researcher** — web search + read_url + summarization-heavy prompt
- **Operator** — computer_use foregrounded, automation tilt
- **Drone-Brain** (placeholder — wires JP01 capability profile when it lands)

This is **lower-effort than the marketplace** because it's a curated
in-tree set, not a network service. And it complements the marketplace
(persona packs at setup-time → marketplace for skill add-ons later).

**0.3.0 fit:** clean. Probably one week of work.

### B. Deep Research surface *(medium signal, medium effort)*

Odysseus's "Deep Research" is structured multi-step web work with
progress UI + citation roll-up. We have the *primitives* (`web_search`,
`read_url`, kanban) but no opinionated "research run" command that
turns a question into a structured 5–10 step search + read + synthesize
+ cite plan.

This is just a built-in skill that wraps existing tools:
- decompose the question into sub-queries (LLM)
- fan out N web searches
- pick top results, read_url each
- summarize per source
- synthesize with explicit citations
- save the artifact to workspace/research/

Even better: have it use the kanban so the user can watch the run
expand into cards.

**0.3.0 fit:** maps onto skills the agent could self-develop; a curated
v1 from us seeds the pattern. Probably 3–4 days.

### C. Email as a fourth messaging bridge *(medium signal, low-medium effort)*

Architecturally it's just another adapter for `messaging_gateway.py`.
We already have the multi-channel daemon pattern; adding email is
follow-the-template work, not new architecture. Local IMAP/SMTP, no
cloud SDK needed.

Risks: drafting → sending requires the same ask-user confirmation
pattern we use for iMessage's destructive ops. Probably handle by
making "send" tier-gated to EXTERNAL_EFFECT (which already exists).

**0.3.0 fit:** plausible. ~1 week if we scope to "read + draft", not
"send autonomously."

### D. Theme system across surfaces *(low signal for us right now, low effort)*

Odysseus theming is a polish thing. We have TUI palettes already.
Tray has none, the future GUI will need them. Worth defining a shared
theme tokens file (colors, accents) so TUI + tray + GUI + web pull from
one source — but this is housekeeping, not headline 0.3.0.

**0.3.0 fit:** **defer** unless the GUI MVP needs it; bundle into
GUI 0.3.0 work if so.

### E. Document editor *(low signal, high effort) — SKIP*

Reason: building a markdown editor surface is a real product on its
own. Doesn't move the embodied-AI thesis forward. The Odysseus version
isn't differentiated enough to be worth porting.

If we ever want this, the path is: GUI ships → markdown view of
workspace files comes for free → the agent can `edit_file` against
what the user has open. That's already the design vector; no new work
needed in 0.3.0.

### F. Image gallery *(low signal, low-medium effort) — DEFER*

We have `generate_image`. A gallery is browse-over-files. The GUI will
expose this naturally once it lands. Not a 0.3.0 line item.

### G. Web surface as the primary chat UI *(thesis conflict) — SKIP / RETHINK*

Tempting. But:
- We already have TUI (production-grade), tray (live), GUI (next).
- A web surface is a *fourth* chat surface to maintain.
- The daemon already supports it — `chat.send` is transport-agnostic, a
  tiny FastAPI bridge could expose it. So the *capability* is there;
  the *cost* is maintenance + design surface area.

**0.3.0 fit:** **skip as core deliverable**, but earmark a 30-line FastAPI
shim as a "remote dashboard" stretch goal. Don't commit to it as a
first-class surface.

### H. Landing page polish as a deliverable *(already done)*

Acted on this — `docs/index.html` is now in the repo. No further action.

---

## 3. 0.3.x release ladder

Locked the night of 2026-06-02 — four focused minor releases, each
standing alone and each building on the last. No new agent capabilities
land until the Apple-native foundation is in place (0.3.0). After that,
the skill ecosystem (0.3.1) → visual presence (0.3.2) → personality
layer (0.3.3) sit on a stable foundation.

| | What | Why this order |
|---|---|---|
| **0.3.0** | Swift + Apple-native rebuild | The 0.2.x tray + Terminal-spawn + Python-audio stack hit its architectural ceiling. Native app + AVAudioEngine + ANE-accelerated Whisper retires it. **Foundation must be solid before piling features on.** |
| **0.3.1** | New skills pipeline | Three-tier runtime resolution (`agent → shared → official`) + `propose_skill` / `accept_skill` + marketplace path. Detailed in [[skill_sharing_pipeline]]. Riding on the now-stable Swift surface. |
| **0.3.2** | Digital agent avatar | Visual presence on the desktop — floating/character widget. Inspired by Lilith's pill launcher + Claude Code's design language. Wakeable via Option+Space, auto-hides on focus loss. Uses the Swift app's existing window infra. |
| **0.3.3** | Agent persona system | Persona packs at setup (Lilith / Coder / Researcher / Operator) + runtime persona switching surface in the Swift app. Closes the "what is this agent FOR?" cold-start gap Odysseus's cookbook surfaces. |

Each release in detail below — 0.3.0 first (this is what we're
building now), then summaries of 0.3.1-0.3.3 for forward visibility.

## 4. 0.3.0 — Swift + Apple-native rebuild (the current target)

The 0.3.0 line, ordered. Each item lists what it is, why, scope, fit.

### Tier 1 — must-ship in 0.3.0

#### 1.1 Swift + SwiftUI desktop app — **the 0.3.0 headline**

**Reference architecture: Ollama Desktop.** Open-source, single-binary
Mac-native app, Swift UI on top of a separate compute backend, talks
to it over a local socket. Tray icon + window + model lifecycle, no
Terminal in sight. Same shape Claude Desktop and ChatGPT Desktop use,
but proven in an open-source context with constraints close to ours.
Our daemon is the equivalent of their `ollama serve`; our Swift app
replaces what they call `Ollama.app`. **We are not inventing this
pattern. We are adopting a battle-tested one.**

- **Why:** The 0.2.x tray-spawns-Terminal model is fundamentally
  fragile. Every "Open TUI / Open Voice" patch we shipped in 0.2.6
  was working around the architectural fact that rumps can't open
  windows, so we forward env vars to AppleScript-spawned shells.
  That dead-ends. A native Mac app owns its tray icon + chat window
  + voice surface in **one process** and talks to the existing Python
  daemon over the socket.
- **Why Swift (vs PyQt6 / Tauri / Electron):**
  - **Smallest footprint:** ~10 MB binary, ~40 MB RAM idle. Compare
    Electron's ~150 MB / 250+ MB.
  - **Real Metal access** — not just "the UI renders via Metal" (which
    every stack gets for free on macOS) but direct `MTLDevice`,
    Metal Performance Shaders, and the **ANE (Apple Neural Engine)**.
  - **Audio rebuild as a side-effect:** AVAudioEngine replaces
    `sounddevice → PortAudio → CoreAudio`. The wedging-CoreAudio
    bug class (BenQ-stuck-AUHAL, etc.) doesn't exist with the native
    framework. Voice processing mode brings free hardware AEC —
    likely deletes the speexdsp dependency.
  - **CoreML-accelerated Whisper:** whisper.cpp's CoreML variant
    runs the encoder on the ANE, **2-3× faster** than pywhispercpp.
    Two-pass `base.en + medium.en` could collapse to single-pass
    `large-v3` at the same wall time.
  - **Native AirPods / Bluetooth routing:** AVAudioSession route
    notifications handle hot-unplug, mid-call connect, etc. — the
    current Python audio loop has none of this.
  - **AVSpeechSynthesizer / SFSpeechRecognizer** become available
    as Apple-native STT/TTS options alongside Whisper / Kokoro.
- **What this kills:**
  - rumps tray (replaced by `NSStatusItem`)
  - prompt_toolkit + rich-tui (replaced by SwiftUI chat surface)
  - voice_loop's Terminal-flow + speexdsp + half of the AEC code
  - all of `_open_terminal_running` / `_shell_env_prefix` etc. in
    `interfaces/tray/macos.py` — the whole shell-spawn dance
- **What the daemon does:** nothing changes. The Python agent core
  stays exactly as it is. Swift app connects via the existing
  `chat.send` / `chat.subscribe` / `status.snapshot` verbs. The
  protocol you already built is the right interface.
- **Cross-platform later:** PySide 6 (Qt) stays in the strategy doc
  as the *future* fallback if/when JROS needs a Linux client for a
  non-JP01 reason. Mac-first means Mac-deep first. JP01 itself
  doesn't need a UI on the Jetson side — the Jetson is a sensor +
  motor I/O node, the brain stays on the operator's Mac.
- **Shape (MVP):**
  - `JaegerOS.app` bundle in Applications
  - Tray icon (`NSStatusItem`) with: Open Chat / Open Voice /
    Start Daemon / Stop Daemon / About / Quit
  - Chat window (`NSWindow` + SwiftUI `View`) with:
    markdown rendering, code-block highlighting, scrollback,
    `❯` prompt input, status bar (model · ctx % · turns), slash
    commands. Same visual rhythm as today's rich-tui.
  - Voice push-to-talk panel (AVAudioEngine + whisper.cpp.coreml
    + Kokoro called via subprocess for v1, native AVSpeechSynth in
    v2). Voice processing mode for AEC.
  - Daemon lifecycle: `Process` spawns/stops the Python daemon,
    waits for socket, shows boot progress.
- **Effort:** ~5-6 weeks for MVP. Real work — but it deletes more
  code than it adds, and retires the entire shell-spawn-Terminal
  class of bugs permanently.
- **Surface preserved:** Existing TUI (`./run.sh --instance NAME`)
  stays as-is. CLI surface unchanged. Power users on a remote SSH
  session still use the TUI. The desktop app is the **default for
  Mac operators**, not the only surface. (See the
  [[feedback-preserve-0.1.0-surfaces]] standing rule.)
- **Risk:** Swift is a second language in the project. Mitigation:
  the Swift code is purely UI + AVAudioEngine plumbing. All agent
  logic, tools, memory, skills stay in Python. Anyone who knows
  the Python side never needs to touch Swift.

#### 1.2 Persona Packs at setup
- **Why:** Lower the cold-start cliff for new users; show that JROS is
  for more than just a single companion.
- **Shape:** A new wizard step *before* the existing 6 — "pick a
  starting pack." Packs ship in `jaeger_os/personas/`. Each pack is a
  YAML that the wizard merges into the new instance's config + writes
  the persona file + flags a starter skill set.
- **Initial packs:** Lilith / Coder / Researcher / Operator. Drone-Brain
  scaffolded but disabled until 0.5.x.
- **Effort:** ~1 week including the four packs.

#### 1.3 Skill sharing pipeline — runtime layer
- **Why:** Operator asked. Today an agent can edit its own skills;
  there's no path for one agent's improvement to reach another agent
  on the same machine, much less the fleet.
- **Shape:** See [[skill_sharing_pipeline]] (companion doc). Three-tier
  resolution: official (read-only) → shared (operator-gated promotion)
  → per-instance (agent-writable). Adds `propose_skill` + `accept_skill`
  agent verbs and an operator-side `./run.sh skill accept` review CLI.
- **Effort:** ~1 week (mostly the loader changes + the operator review
  UX; the storage is just directories).

#### 1.4 Deep Research v1 skill
- **Why:** Showcases the agent loop on a structured multi-step task and
  fills the obvious "I asked a question, please go research it" gap.
- **Shape:** Ships as a default skill (`skills/research/v1/`), uses
  kanban for progress, writes a markdown artifact under
  `workspace/research/<topic>/`.
- **Effort:** ~3–4 days.

### Tier 2 — strong-want, slot if there's room

#### 2.1 Email bridge
- **Why:** Fourth messaging surface, completes the "every channel" pitch.
- **Shape:** Local IMAP read + draft (SMTP send tier-gated to
  EXTERNAL_EFFECT). Adapter under `jaeger_os/plugins/email/`.
- **Risk:** IMAP idle is finicky; expect to drop to polling for v1.
- **Effort:** ~1 week.

#### 2.2 Vision pipeline validation
- **Why:** We have `describe_image` (Moondream2) and `generate_image`
  (SDXL). They're plumbed but lightly exercised. Real benchmark + at
  least one default skill that uses them before JP01 needs vision.
- **Shape:** Add to `dev/benchmark/`. Smoke test in CI. One default
  skill (`describe_workspace_image` or similar).
- **Effort:** ~3 days.

### Tier 3 — nice-to-have

#### 3.1 FastAPI dashboard shim
A tiny `daemon/web.py` that proxies `chat.send` over HTTP, serves a
minimal HTML chat surface from `docs/dashboard/`. **30 lines, no SPA.**
Ship as opt-in; not promoted as a primary client.

#### 3.2 Shared theme tokens
`jaeger_os/ui/theme.py` — color tokens consumed by TUI palettes, tray
icons (it has two), and the GUI when it lands. Slot into 1.1.

#### 3.3 Image gallery view
Defer to GUI. Don't commit to it.

#### 3.4 `run_self_test` + `audio_reset` agent tools
Tiny QoL — leftover from 0.2.6 dev. Each one is a few hours.

### Explicitly out of 0.3.0

- Web surface as a first-class client (revisit in 0.4.x with hardware
  nodes already pulling toward a dashboard).
- Document editor.
- Plugin marketplace launch — needs the marketplace repo to exist first
  ([[marketplace_spec]] has the dependency list).
- Cookbook of 270 recipes — that's a curation rabbit hole, not what
  moves embodied-AI forward.

---

## 4. Positioning takeaways (the JROS thesis stays sharp)

Reviewing Odysseus surfaced a positioning trap to avoid: the
"local-first AI workspace" framing makes us look like a competitor to
a consumer chat app. We aren't.

**JROS is the operating framework for real-world agentic AI.** The
chat surface is a *byproduct* of having a great agent loop — it's not
the headline. Headline is: same brain runs on a Mac today, on JP01's
drone hardware next, on a humanoid arm after that. One runtime, many
bodies. Embodied. Open.

Anything we add for 0.3.0 should pass the test: *does it move us
toward agents driving real hardware?* If the answer is no, it's
probably Tier 2 or skip.

The landing page already reflects this corrected framing. The
roadmap above does too. If a future review of a similar consumer
project pulls us toward "let's add another chat feature" — refer back
to this section.

---

## 5. What we explicitly didn't copy

For the record so we don't drift:

- **Recipe-as-model-swap.** We don't expose model-picking as a per-turn
  UI. The daemon's awake/asleep cycle is the right abstraction; adding
  per-turn model swaps creates KV-cache churn for marginal gain.
- **Catalog of 270 personas.** Curation cost > value. Ship 4 good ones.
- **Web-as-primary.** TUI is the production surface, GUI is next, web
  is a stretch shim. Order matters.
- **The "all in one app" framing.** We're a runtime, not an app. The
  framing is "JROS lets you build agents," not "JROS *is* an agent."

---

## 6. Open questions for the operator

1. **Persona packs** — agree with the four (Lilith / Coder / Researcher /
   Operator) or want a different mix? Drone-Brain stub OK?
2. **GUI MVP scope** — floating chat only, or do you want the tray-menu
   tasks (open dashboard, view memory, switch instance) wired in too?
3. **Email bridge — read-only first, or draft+send?** Send adds a
   confirmation-flow design call we should think through before
   committing.
4. **0.3.0 timing** — there are ~5–7 weeks of solid work above (Tier 1
   alone). Do you want a 0.3.0 → 0.3.1 split (GUI as 0.3.0, the rest as
   0.3.1) or one big drop?
