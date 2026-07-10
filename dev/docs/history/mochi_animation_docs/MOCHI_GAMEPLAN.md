<h1 align="center">Mochi — Game Plan</h1>

<p align="center"><em>An embodied AI character: a desk companion that talks, emotes, and animates — built on the jaeger_os runtime.</em></p>

> Roadmap & architecture reference (v5, on the jaeger_os base). Mochi is both a
> **standalone product** people can run, and the **nest** where embodiment nodes
> are grown and hardened before they're imported into main JROS.
> This doc is the source of truth for *what we're building and in what order*.

---

## 1. What Mochi is

Mochi is an **AI character you can see and talk to**. Same spirit as the *Dasai
Mochi* desktop toy and the wave of "AI avatar" companions — but where most of
those are closed, cloud-bound, and single-character, Mochi is **local-first,
open, and built to host any character** on hardware you own.

Two jobs, one codebase:

1. **A standalone companion app** — a little animated character on your desktop
   (and later on real hardware: an LED face, a screen-headed robot) that has a
   personality, speaks, reacts, and runs an actual agent loop with tools.
2. **The node nursery for JROS** — every capability is a self-contained **node**
   on the jaeger_os bus. Once a node is solid in Mochi, it's imported wholesale
   into main JROS. Mochi is where embodiment gets proven; JROS is where it ships
   across every body.

**Why it exists:** the good versions of this (EMO, Eilik, Divoom, Anki Vector,
VTube Studio / Live2D, HeyGen-style talking avatars, Character.AI personas) are
mostly **private and proprietary**. We want our **own method**, reference what
exists, and make the **publicly available option** — runnable offline, ownable,
extensible.

---

## 2. The one principle: everything is a node

Mochi is a jaeger_os **implementation**, not a fork. The root *is* `jaeger_os/`
(the agent loop, tools, skills, memory, transport, bus — the brain + nervous
system). Every Mochi-specific capability lives under `nodes/<name>/` and talks
**only over the bus** (topics in, topics out). Nothing reaches into another node.

That's what makes a node importable into JROS: it's a closed box with a topic
contract. To adopt a node in JROS you copy `nodes/<name>/` and add one
`[[node]]` block to the app manifest — no surgery.

**Node contract** (each `nodes/<name>/`):
```
nodes/<name>/
  node.py          # a jaeger_os Node subclass: subscribes/publishes topics, lifecycle
  manifest.toml    # declared topics in/out, config schema, asset needs
  <engine>/        # the unique code for this feature (the value)
  assets/          # asset contract (formats, catalog schema) — data, not code
  tests/           # the node's own tests (Mochi tests nodes; JROS tests the framework)
```

**Carry-over debt from the archive:** the old Mochi nodes spoke **raw ZMQ
PUB/SUB** (`node.animation.frame`, etc.). The jaeger_os base has its own
bus/transport (`/sense/*`, `/act/*` topics, the chassis in-proc bus). **Phase 0
re-homes the nodes from raw ZMQ onto the jaeger_os node/topic API** — that single
move is what turns "old Mochi code" into "JROS-importable nodes."

---

## 3. The node map

```
                         ┌──────────────── PERSONA NODE ────────────────┐
                         │  who the character is: trait layers, prompt   │
                         │  rendering, persona library, live trait edits │
                         └───────────────┬───────────────────────────────┘
                                         │ identity + emotional bias
                                         ▼
   user voice ──► VOICE NODE (STT) ──►  jaeger_os AGENT (brain) ──► reply text
                                         │  + emotion/expression cue
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                     ▼
              VOICE NODE (TTS)     ANIMATION NODE         (emotion bus)
              speak + visemes  ──► pick & play the    ◄── tags like <play happy/>
                    │                animation/expression
                    │ amplitude/visemes  │ rendered frames
                    └─────────►  AVATAR NODE  ◄────────┘
                                 the on-screen body: window/skin/face,
                                 lip-sync, blits frames, drag, packs
                                         ▲
                                 MEDIA NODE: assets, catalog, decoders, packs
```

Flow in one line: **Persona** says who you are → **Agent** decides what to say +
an expression → **Voice** speaks it + **Animation** plays the matching motion →
**Avatar** shows it on screen, lips synced to the voice → all fed by **Media**.

---

## 4. The nodes

### 4.1 Animation Node  `nodes/animation/`
*The most mature thing in the archive — reuse aggressively.*

- **Does:** turns a named expression ("happy_blink", "rainbow") into rendered
  frames. Two control paths: LLM tags and operator/CLI commands.
- **Reuse from `archive/mochi-v4/nodes/animation/`:**
  - `llm_command_parser.py` — stable grammar: `<play name="happy"/>`,
    `<play>angry</play>`, `[play:idle]`, `<mode name="rainbow"/>`, `<stop/>`.
    Copy nearly as-is.
  - `plugin_core/mscript_engine.py` — `.mscript` declarative timeline
    (`[Resources]` key map + `[Main]` `MEDIA K[1] D[2.0]` / `WAIT` / `EVENT`),
    with `D[auto]` duration inference from media. Clean — keep.
  - `animations/` handlers + `decoders/` — gif / video / sprite / bitmap / image
    / math, on a `DecodedMediaAnimation` base with fit/fill/stretch framing.
    Production-grade; keep.
  - `plugin_core/gfx.py`, `font.py`, `color_utils.py` — numpy primitives + 5×7
    font, no bus deps. Vendor directly.
- **Build:** re-home `node.py` from ZMQ onto a jaeger_os Node; finish the
  half-built bits (sprite-sheet animated mode, keyframe/EVENT timeline, a TEXT
  handler over the existing font); sandbox the `math` dynamic-Python handler.
- **Topics (new):** in `sense/expression` (emotion cue), `act/animation` (play/
  stop/mode); out `sense/animation.frame` (frames), `sense/animation.state`.

### 4.2 Avatar Node  `nodes/avatar/`
*The body. Distinct from animation: animation is the **content**, avatar is the
**embodiment** it plays on.*

- **Does:** renders frames to the on-screen character and owns the character's
  physical presentation — window, skin/bezel, position, lip-sync.
- **Reuse:** `archive/.../interfaces/mochi_vdisplay_player_qt.py` — frameless,
  transparent, per-pixel-alpha Qt overlay, always-on-top, draggable. The toy.
- **Build:** subscribe to `sense/animation.frame`; lip-sync to the Voice node's
  amplitude/visemes; skin/bezel system (CRT, JDM dash, user packs). This node is
  the seam for **future avatar engines**: today a frame blitter; later a Live2D /
  3D / diffusion-driven face behind the *same* topic contract.
- **Why its own node:** in JROS the "body" swaps (desktop window → LED matrix →
  robot screen) while animation/persona stay put. Keeping avatar separate is what
  makes "one character, many bodies" real.
- **Topics:** in `sense/animation.frame`, `sense/voice.viseme`; out
  `act/avatar` (window controls), `sense/avatar.state`.

### 4.3 Persona Node  `nodes/persona/`
*Who the character is. Mature in the archive as `lilith_persona_kit` — portable.*

- **Does:** holds the personality model and renders it into the agent's system
  prompt; lets you author, swap, and live-tune characters.
- **Reuse from `archive/mochi-v4/salvage/lilith_persona_kit/`:**
  - `persona_system/persona.py` — four trait layers (**HEXACO** big-five+honesty,
    Fallout **SPECIAL**, **Expression** style, **Domains** interests), plus
    `custom_instructions` / `speech_patterns` / `backstory`. 7-band slider→prose
    rendering with neutral zone. Frozen dataclasses, V3/V4 JSON round-trip. Keep.
  - `gui/studio_window.py` + `radar_chart.py` — the Persona Studio (slider grid +
    spider chart). Becomes Mochi's character editor.
  - `persona_skill/` — MCP skill: `read_traits`, `adjust_trait`, `bulk_adjust`
    (the character can adjust *itself*). Re-expose via JROS's skill/MCP layer.
  - `personas/*.json` — glados, lelouch, etc. Seed library.
- **Build:** map persona → emotional bias on `sense/expression` (so traits steer
  which animations fire); hot-reload on change; tie persona to a default voice.
- **Topics:** in `act/persona` (select/adjust); out `sense/persona.changed`,
  `sense/expression` (mood bias).

### 4.4 Voice Node  `nodes/voice/`
*The talking. The deps are already installed and `jaeger doctor`-green.*

- **Does:** speaks replies (TTS) and listens (STT + wake-word), as the character.
- **Reuse:** jaeger_os already ships the engines — **kokoro** (TTS), **whisper**
  (STT), **openwakeword** + webrtcvad (wake/VAD), AVAudioEngine I/O. The Voice
  node is the **character wrapper** over them, not a reimplementation.
- **Build:** per-persona voice + prosody; emit **amplitude/visemes** on
  `sense/voice.viseme` so the Avatar node can lip-sync; barge-in (stop speaking
  when the user talks); tie speaking state into expression (talking animation).
- **Topics:** in `act/speak`, mic stream; out `sense/voice.viseme`,
  `sense/voice.state` (listening/speaking), transcript → agent.

### 4.5 Media Node  `nodes/media/`
*The supply chain feeding animation + avatar.*

- **Does:** owns the asset catalog, decoders, and **packs** (shareable character/
  animation bundles). The reason 167 animations are addressable by name.
- **Reuse:** `archive/.../assets/CATALOG.json` + `tools/build_catalog.py`,
  `build_thumbnails.py`, and the content editors (`mscript_editor_gui.py`,
  `sprite_editor_gui.py`, `bitmap_editor_gui.py`).
- **Build:** a versioned **pack format** (idle + reaction pools + skins + audio +
  persona, one bundle), catalog hot-reload, a thumbnailer, and a public pack
  index later (the "others can use it" surface). This is the node that makes
  Mochi a *platform*, not one toy.
- **Topics:** out `sense/catalog` (available expressions/packs); in `act/catalog`
  (load/reload pack).

---

## 5. Phased roadmap

Order is chosen to get a **visible, talking character on screen fast**, then
deepen. Each phase ends with at least one node fully re-homed onto the jaeger_os
bus + its own tests, so it's immediately JROS-importable.

| Phase | Goal | Nodes | Outcome |
|------|------|-------|---------|
| **0 · Foundation** | One node alive on the jaeger_os bus | (animation, thin) | Prove the node contract: a `[[node]]` in `jaeger.toml` subscribes a topic, publishes frames. Kills the ZMQ dependency. |
| **1 · It moves** | LLM-driven character on screen | Animation + Avatar | Agent emits `<play happy/>`, the mini-window character plays it. The MVP everyone can see. |
| **2 · It's someone** | Personality | Persona | Pick GLaDOS vs a custom persona; traits steer prompt + which expressions fire. Persona Studio editable. |
| **3 · It talks** | Voice + lip-sync | Voice | Speaks replies in a persona voice, listens on wake-word, mouth synced to amplitude. The "companion" lands. |
| **4 · It's a platform** | Content + configurator | Media + companion app | Catalog/packs, content editors, the Companion app (browse/pick/scene). Others can author + share packs. |
| **5 · It's expressive** | Advanced embodiment | Avatar++ | Scenes/triggers/scheduling; richer faces behind the same avatar contract (Live2D / 3D / diffusion); robot/LED bodies. |

**Cross-cutting, every phase:**
- **Emotion/expression bus** (`sense/expression`) is the shared spine — persona
  biases it, agent sets it, animation + voice consume it. Define it early (Phase 1).
- **JROS-import checkpoints:** at the end of each phase, the finished node is
  copied into JROS behind its topic contract and smoke-tested there.
- **Truthful status:** anything not built is labelled `(planned)`; a node isn't
  "done" until it's re-homed off ZMQ, tested, and JROS-imported.

---

## 6. Competitive reference (define the public alternative)

| What exists | What's closed about it | Mochi's open answer |
|---|---|---|
| **Dasai Mochi** desktop toy | Fixed character, closed | Any character, open packs, scriptable |
| **EMO / Eilik / Vector** | Proprietary hardware + cloud | Local agent, runs on hardware you own |
| **Divoom** pixel displays | App-locked content | Open mscript/sprite/bitmap pipeline |
| **VTube Studio / Live2D** | Tracking-only, no brain | Real agent loop + tools behind the face |
| **HeyGen / D-ID** talking avatars | Cloud, per-minute, no autonomy | On-device TTS + persona + autonomy |
| **Character.AI** personas | Cloud, text-only, no body | Local persona model **with** a body + voice |

Our wedge: **local-first + an actual agent (tools, memory, autonomy) + an open
character/pack format + one character across many bodies.** Nobody public does
all of those at once.

---

## 7. What's Mochi-only vs imported to JROS

- **Imported to JROS** (the nodes): persona, voice, animation, avatar, media —
  the embodiment capabilities, behind topic contracts.
- **Mochi-only** (the product shell): the Companion configurator app, the pack
  marketplace/index, the desktop-toy packaging, content editors. JROS consumes
  the nodes; it doesn't need Mochi's storefront.

---

*Status: structure + env ready (jaeger_os base on a 3.11 venv, `jaeger doctor`
green; run `jaeger setup` to bind a model). All five nodes are still in
`archive/mochi-v4/` awaiting re-home onto the bus — Phase 0 is next.*
