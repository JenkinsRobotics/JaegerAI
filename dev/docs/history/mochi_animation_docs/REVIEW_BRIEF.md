# Mochi — review brief for an external reviewer

**Date:** 2026-06-10
**Branch:** mochi-v4 (38 commits ahead of main)
**Author of the code under review:** Claude, working with the operator
**Audience:** an LLM-driven code-review tool, or a senior reviewer
**Goal of this document:** give you enough context to do a thorough,
opinionated review of where Mochi is + where it should go next.
Copy-paste this entire file into the review tool's input.

---

## 1. What Mochi is

A desktop application + framework for **animated character
displays**, inspired by the Dasai Mochi3 toy.  It renders
expressive animations (faces, characters, scenes) into a small
virtual display, with the operator picking what plays.

Not a single product — a layered framework that supports several
operator modes:

| Mode | Operator role | LLM role | Today |
|---|---|---|---|
| **Manual** | Picks animations by hand from a library | Off | ✓ working |
| **Scripted** | Authors mscript sequences | Off | ✓ working |
| **Event-driven** | Binds triggers (time / ZMQ / file) to animations | Off | planned |
| **AI-driven** | Conversational; LLM picks animations | Active brain | ✓ wired, parked |

Part of the **Jenkins Robotics** stack:
[Jenkins Robotics](https://jenkinsrobotics.github.io) ·
[Discord](https://discord.gg/sAnE5pRVyT) ·
[GitHub](https://github.com/jonathanjenkins).  Mochi is the
animation pipeline testbed for JROS — lessons learned here merge
back into the larger robot OS.

## 2. Why we're building it (the bigger picture)

Three audiences:

1. **The operator (Jonathan)** wants a working desktop toy that
   he controls, demos to his audience, and uses on streams.
   Day-one is "I want to click a happy face and see one."
2. **End users** who download Mochi for their own desktops want
   curated, easy-to-pick character packs.  They never write code.
3. **Animation educators + makers** want a hands-on tool that
   teaches animation techniques — every type Mochi renders (GIF
   / sprite / video / math / declarative) is also a chapter in
   the Learn tab.

These are not mutually exclusive — the SAME codebase, with
different UI surfaces, serves all three.

## 2.1 Architecture rule: logic outlives the GUI

Mochi should treat PySide6 as a replaceable shell, not as the home
of product logic. Today the surface is Qt; tomorrow it may be Swift,
TUI, web, or a robot-attached panel. The universal behavior must live
outside widgets:

- Renderer behavior, animation selection, scripts, LLM command
  parsing, asset catalog rules, persistence, and bus protocols belong
  in nodes, `core/`, `agent/`, `nodes/animation/`, or small pure
  service modules.
- GUI files should render state, collect user intent, and translate
  that intent into typed bus messages or narrow service calls.
- Toolkit-specific bridge code is allowed, but should be thin:
  Qt signals, timers, model adapters, and widget lifecycle belong in
  the surface; domain decisions do not.
- A future Swift surface should be able to reuse the same catalog,
  commands, nodes, scripts, and message contracts without porting
  PySide widget classes.

Current status: the runtime core mostly follows this rule
(`nodes/animation`, `agent`, `transport`, `app`). First cleanup pass
extracted catalog filtering, recent persistence, player settings, and
animation command resolution into `core/companion_services.py`. The
companion still owns some logic that should gradually move behind
toolkit-neutral services/adapters, especially live preview renderer
reuse and process launching.

## 3. What's shipped on mochi-v4 (current state)

### Core framework

```
mochi-v4/
├── agent/
│   ├── node.py                       ← subprocess entrypoint
│   ├── loop/                         ← transport-neutral turn logic
│   ├── adapters/                     ← Ollama + mock adapter slots
│   ├── tools/                        ← deterministic agent tools
│   ├── prompts/ and personas/        ← prompt/persona assembly
│   └── README.md                     ← commands + adapter notes
├── nodes/
│   └── animation/                    ← 7 renderer backends:
│       ├── node.py                       gif / sprite / png /
│       ├── animations/                    bitmap / math / video /
│       │   ├── gif_handler.py            mscript
│       │   ├── sprite_handler.py     ← upgraded w/ grid +
│       │   ├── image_handler.py           named_frames support
│       │   ├── bitmap_handler.py
│       │   ├── math_handler.py
│       │   ├── video_handler.py
│       │   └── decoders/
│       ├── plugin_core/
│       │   └── mscript_engine.py     ← Fanuc-inspired DSL
│       └── llm_command_parser.py     ← parses LLM reply tags
├── transport/                        ← ZeroMQ bus
│   ├── broker.py                         XPUB ↔ XSUB proxy
│   ├── topics.py                         topic conventions
│   ├── messages.py                       Msg envelope schema
│   ├── zmq_manager.py                    helpers
│   ├── node_base.py                      MochiNodeBase
│   └── node_template/                    shared bootstrap
├── core/                             ← shared infra
│   ├── host_monitor.py                   process supervisor
│   └── plugin_registry.py                config-driven launcher
├── gui/
│   ├── mochi_companion.py            ← THE GUI — 2700 lines, Qt
│   ├── mochi_health_service.py           shared health subscriber
│   ├── mochi_vdisplay_player_qt.py       frameless mini window
│   ├── mochi_gui.py                  ← legacy Tk panel (disabled)
│   ├── mochi_vdisplay.py + _player.py    older viewers
│   └── llm_chat_gui.py                   LLM chat window
├── tools/
│   ├── build_catalog.py                  walks assets/, makes
│   │                                       CATALOG.json
│   ├── build_thumbnails.py               first-frame extract →
│   │                                       assets/thumbs/*.png
│   ├── scaffold_props.py                 writes .props.yaml stubs
│   ├── build_system_prompt.py            generates LLM prompt
│   ├── bitmap_editor_gui.py              content editors
│   ├── sprite_editor_gui.py
│   ├── mscript_editor_gui.py
│   ├── mochi_studio.py
│   └── launch_legacy_tk.sh               rollback path
├── assets/
│   ├── CATALOG.json                  ← 167 entries indexed
│   ├── packs/                            real packs land here
│   │   └── README.md                     (operator authoring)
│   ├── skins/
│   │   └── tv1/                      ← first formal skin
│   │       ├── body.png
│   │       └── meta.yaml
│   ├── thumbs/                       ← 166 cached PNGs (~776 KB)
│   ├── pinned.json                       sidebar shortcuts
│   ├── recent.json                       last-fired animations
│   ├── SYSTEM_PROMPT.txt                 LLM system prompt
│   ├── animations/                       6 declarative JSON
│   ├── bitmaps/ + bmps/                  5 + 2 bitmaps
│   ├── gifs/                             68 GIF clips
│   ├── icons/ + png/                     4 + 6 static images
│   ├── math/                             26 procedural Python
│   ├── mscripts/                         18 scripted sequences
│   ├── procedural/                       1 procedural
│   ├── video/                            31 video clips
│   └── *.props.yaml                  ← 167 sibling sidecars
└── docs/
    ├── OPERATOR_PRODUCT_PLAN.md          comparable-product research
    ├── PACK_CONVENTION.md                pack schema spec
    ├── SKIN_CONVENTION.md                skin schema spec
    ├── ASSET_PROPERTIES.md               sidecar schema spec
    ├── SUPERSEDE_TK_PLAN.md              Tk → companion migration
    ├── ANIMATION_REVIEW.md               LLM-track audit
    ├── future_multi_timeline.md          mscript split idea
    └── learn/                            9 chapters: history +
                                            how each animation
                                            type works + how
                                            Mochi renders it
```

### Companion app surfaces (Qt/PySide6, Wondershare-inspired)

| Tab | Status | What works |
|---|---|---|
| **Home** | Working | Hero card w/ active animation, recent strip, Active-nodes table w/ per-node Stop + Reset |
| **Library** | Working | 167 thumbnail cards, three filter chips (Mood / Type / Curation), search, click → fires |
| **Packs** | Working | Empty state today; pack-card grid + slot detail + Set Active when packs land |
| **Scenes / Triggers / Schedule** | Stub | Empty drop-zone state — Phase B/C of original plan |
| **Editors** | Working | 4 tiles → Sprite / Bitmap / MochiScript / Mochi Studio subprocesses |
| **Learn** | Working | 9 markdown chapters covering each animation type |
| **Settings** | Working | Skin list + advanced toggle revealing Renderer (colour, canvas size, reset) and Diagnostics (raw cmd, quit node) |

Plus persistent UI: sidebar (logo + nav + Pinned shortcuts + JR
promo card), top toolbar (status pill + Stop button + community
shortcuts + Open Mini Window).

### Recently completed migrations

- **Tk → Qt supersede (6 phases)** — every legacy Tk panel feature
  now has a home in the companion.  `mochi_gui.py` is disabled in
  config but kept in tree as rollback.
- **HealthService extraction** — shared backend, Qt signals to all
  consumers.
- **167 .props.yaml sidecars scaffolded** — 1 hand-authored
  (happy_blink), 166 stubs.
- **Pack convention + Skin convention + Asset-properties
  convention** — formal schemas in `docs/`.

## 4. The framework's design language

Read `docs/OPERATOR_PRODUCT_PLAN.md` for the research-driven
position.  Short version:

- **Wondershare UniConverter** is the visual reference — sidebar
  + card grid + accent purple + lots of whitespace
- **VTube Studio** is the trigger-binding reference (later phase)
- **Eilik / EMO** are the "modes / scenes" reference
- **Shimeji** is the desktop-pet floating-toy reference

The companion is the configurator; the mini window is the toy.
Three surfaces with distinct purposes:

1. **The toy** — frameless ~300px always-on-top mini window
2. **The companion** — full configurator (what mochi-v4 ships)
3. **The dev tools** — content editors (live in `tools/`)

## 5. The 7 animation backends — design ideas

| Type | Renderer file | Source | Trade-off |
|---|---|---|---|
| PNG / static | image_handler | stored frame | simplest, no time axis |
| Bitmap (1-bit) | bitmap_handler | packed bits | memory-efficient for embedded |
| GIF | gif_handler | LZW + per-frame timing | classic loops, ~2-4x compressed |
| Sprite sheet | sprite_handler | one image + grid | one disk read, many frames |
| Video | video_handler | MP4 / WebM via imageio | long clips, real video |
| Math (procedural) | math_handler | Python `f(t)` → pixels | algorithm IS the art |
| Eye anim (JSON) | animations/*.json | declarative keyframes | data, not pixels |
| MochiScript | mscript_engine | Fanuc-style DSL | timeline + branching |

Sidecar `.props.yaml` per asset declares: ideal_size,
playback_speed, framing, plus type-specific (sprite grid,
named_frames, math params, etc.).  See
`docs/ASSET_PROPERTIES.md`.

## 6. What's NOT shipped yet — feature gap

Ranked by operator priority (most critical first):

### Tier 1 — packs are the headline missing piece

| # | Feature | Why critical |
|---|---|---|
| 1.1 | **Real character packs** (operator authoring) | Today 0 packs.  The Packs page works but has nothing to show.  Operator is currently authoring; format defined in `docs/PACK_CONVENTION.md`. |
| 1.2 | **Pack thumbnail rendering** | When packs land, the Packs card grid needs real previews, not just first-letter placeholder. |
| 1.3 | **Slot-name standardisation** | Reaction button row (Phase B) wants to bind generic "happy / sad / sleepy" → active pack's slot.  Need a loose vocabulary so packs interoperate. |

### Tier 2 — operator-control depth

| # | Feature |
|---|---|
| 2.1 | **Scene wheel** on Home (Chill / Hype / Focus / Sleepy / Party / Drive / Pomodoro / Festival) — bundles of idle + reaction + audio |
| 2.2 | **Reaction button row** at bottom of Home (Happy / Surprised / Sleepy / Wave / Dance / Stop) — fires the active pack's slots |
| 2.3 | **Trigger bindings table** in the Triggers tab — rows of `Source → Asset` (ZMQ topic, timer, time-of-day, file watcher, MQTT) |
| 2.4 | **Schedule** — cron-style showtimes (weekdays 9-12 → Focus, Fri 5pm → Party) |
| 2.5 | **Tray icon** — Summon / Dismiss / Switch Scene / Mute |

### Tier 3 — content + curation polish

| # | Feature |
|---|---|
| 3.1 | **GIF-preview thumbnails** (hover plays full animation, not just first frame) |
| 3.2 | **Pack auto-detection** from filename prefixes (Chasm*, Dino* etc. are already plausible packs) |
| 3.3 | **In-app sidecar editor** — Library card → right-click → "Edit metadata" opens a form that writes the sidecar |
| 3.4 | **Library favourites filter** — already have pinned sidebar; want a Library filter "pinned only" |
| 3.5 | **Personality slider** (Calm ↔ Hyper) — single dial that modulates idle cadence + reaction probability |

### Tier 4 — bigger pieces

| # | Feature |
|---|---|
| 4.1 | **Multi-channel timeline** (per `docs/future_multi_timeline.md`) — orchestrate LLM / TTS / animation / motor / light tracks |
| 4.2 | **Hardware integration** — Stream Deck + numpad + global hotkey to fire reactions live (VJ workflow) |
| 4.3 | **JROS bridge** — Mochi as the JROS animation node, lessons feed back into the larger stack |
| 4.4 | **Pack marketplace / sharing** — zip with pack.yaml + assets, install from URL |

## 7. What the framework should develop FIRST

Operator-aligned priority for the next session(s):

### Priority A — make a pack ship

The Packs page works but is empty.  Highest-leverage first move
is to get ONE real character pack into the tree so:
- The Packs page shows something
- The Set Active button does something
- We can validate the slot → animation node dispatch path
- We can design the reaction button row against real slots

Cleanest first pack: **eye_default** built from the 6 existing
eye_animation JSONs.  `docs/PACK_CONVENTION.md` includes the exact
authoring commands.

### Priority B — reaction button row on Home (depends on A)

Once a pack exists with named slots (idle / happy / sad / wave /
dance), put a row of big buttons at the bottom of the Home tab.
Click → fire the active pack's matching slot.  Operator's "tap to
react" UX.

### Priority C — Scene definition + scene wheel

A scene bundles {idle pool, reaction pool, audio profile, default
mood}.  Author a few starter scenes (Chill / Hype / Focus /
Sleepy) from existing assets.  Build the scene wheel widget on
Home.  Picking a scene reconfigures the renderer pool.

### Priority D — Triggers tab

Source → Asset bindings.  Sources: time-of-day, wall-clock timer
(every N min), ZMQ topic subscription, file watcher.  Each binding
fires an animation or scene change.  The ZMQ-topic source is the
key one — it turns the bus from plumbing into a feature.

### Priority E — Sunset legacy GUI files for real

`gui/mochi_gui.py` is disabled but still in tree.  Plus
`gui/mochi_vdisplay.py` and `gui/mochi_vdisplay_player.py` are
older viewers superseded by `mochi_vdisplay_player_qt.py`.  Audit
+ delete one release after their replacements are validated.

## 8. Specific questions for the reviewer

These are the answers I (the code author working with the operator)
would find most useful:

### A. Architectural / code-organisation

1. **`gui/mochi_companion.py` is 2700 lines.**  How should it
   split into modules?  Current candidates:
   - `gui/companion/pages/` (one file per Page class)
   - `gui/companion/widgets/` (cards, badges, filter rows)
   - `gui/companion/theme.py` (the QSS block + colour constants)
   - `gui/companion/app.py` (CompanionMain + main())
   - `core/catalog_service.py`, `core/recent_service.py`,
     `core/animation_commands.py` (toolkit-neutral logic)
   - `interfaces/qt_adapters/` (Qt-only model/signal adapters)
2. Are there **Qt resource lifecycle bugs** I haven't caught?  I
   shipped a use-after-free in `_refresh_nodes_table` that
   manifested only when the QTimer ran live.  Are there similar
   patterns elsewhere?
3. **HealthService thread + Qt main thread interaction** — am I
   doing the queue + QTimer dance right, or are there race
   conditions?
4. **Subprocess tracking** — companion launches Mini Window +
   Editors as subprocesses.  Should this be unified into a
   `ProcessRegistry` instead of `_processes: list` in each page?

### B. Schema / convention review

5. **Sidecar `.props.yaml` schema** (`docs/ASSET_PROPERTIES.md`).
   Are the field names good?  Will `type_props` scale to types we
   haven't built yet?  Should there be a JSON Schema for validation?
6. **Pack `pack.yaml` schema** (`docs/PACK_CONVENTION.md`).  Slot
   names are operator-defined per pack.  Is that the right call,
   or should there be a fixed taxonomy?
7. **Skin `meta.yaml` schema** (`docs/SKIN_CONVENTION.md`).  Today
   it's just screen_bbox + window flags.  What does the operator
   need that I'm missing?  Animated bodies?  Multi-screen skins?

### C. Tk supersede completeness

8. **Audit `docs/SUPERSEDE_TK_PLAN.md`** — did I actually migrate
   every feature?  Specifically check the 12-feature audit table.
9. **Phase 6 sunset** — `gui/mochi_gui.py` is disabled but still
   in tree.  Is the rollback path (`tools/launch_legacy_tk.sh`)
   over-engineered?  Should I just delete the file now?

### D. Sprite handler upgrade

10. **`nodes/animation/animations/sprite_handler.py`** got the
    grid + named_frames + animated multi-frame mode in commit
    `357e145`.  Did I get the time→index math right?  Is the
    cell-rect calc correct for any aspect ratio?

### E. Forward direction

11. **Where would YOU start** if you were taking over the
    operator-control build-out?  Tier 1 packs?  Tier 2 reaction
    row?  Something else I missed?
12. **What's the biggest risk** in the current code that would
    bite us in 3 months?
13. **What looks over-engineered** that I should rip out before
    it metastasises?

## 9. Practical context the reviewer needs

- Python 3.11+ (Mochi venv uses 3.13.7 in the operator's setup,
  but 3.11 is a fine target)
- PySide6 for the GUI (LGPL Qt bindings)
- pyzmq for the bus
- PyYAML for everything yaml
- Pillow + imageio for asset processing
- Ollama for the LLM mode (gemma3:12b by default)
- macOS-first; Linux + Windows compatibility incidental but
  desired

To run + test locally:

```bash
cd /path/to/Mochi
source venv/bin/activate
python main.py              # launches broker + animation + llm +
                              # companion (Tk panel is disabled)

# Companion only:
python gui/mochi_companion.py

# Mini window only:
python gui/mochi_vdisplay_player_qt.py

# Build artifacts:
python tools/build_catalog.py        # CATALOG.json
python tools/build_thumbnails.py     # assets/thumbs/*.png
python tools/scaffold_props.py       # missing .props.yaml stubs
```

To explore the codebase:

```bash
git log --oneline mochi-v4 ^09f13c7 | head -50      # 38 session commits
cat docs/SUPERSEDE_TK_PLAN.md                       # migration plan
cat docs/OPERATOR_PRODUCT_PLAN.md                   # product research
cat docs/learn/index.md                             # what's in Learn tab
```

## 10. Output I want from the reviewer

In order of value:

1. **Direct answers to Section 8 questions** — specific, actionable.
   Bullet-point each.
2. **A prioritised list of issues found** — severity × effort.
   Bugs first, then over-engineering / smell, then convention
   nits.
3. **A concrete "if I were you, I'd do X next" recommendation**
   for the next 5-10 commits.  Not a year-long roadmap.
4. **One brutally honest piece of feedback** about something I'm
   doing that's wrong or missing — even if it doesn't fit a
   numbered category.

Don't pad with "what's good" — focus on what to fix + what's next.

---

End of brief.  The branch is `mochi-v4`; latest commit at time of
writing is `a87b006` (community block adopted).  Have at it.
