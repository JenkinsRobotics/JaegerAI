# Mochi operator product plan (2026-06-10)

**Author:** Claude
**Source:** synthesis of Dasai Mochi3 + comparable-product research
**Audience:** operator + future contributors
**Companions:**
- `docs/ANIMATION_REVIEW.md` (the LLM-track review — now parked as optional)
- `docs/future_multi_timeline.md` (operator's mscript-split idea)

## What this is

Operator review (2026-06-10):
> *"a few different gui windows that have a few different things... it
> definitely needs a lot of rework to be considered a real product...
> review what we have today, if possible do some research of the real
> mochi toy and see how they program theirs or similar products and
> lets build out all that"*

This doc reframes Mochi from "LLM-driven animation picker" to
**"operator-controlled animated companion toy."**  The LLM hook
shipped at commits N→N+2 stays as an optional module, not the
headline.

## The big finding from research

> **The real Dasai Mochi3 has no scripting, no app, no desktop tool.**
> It's a curated 70+ animation library with gyroscope-reactive
> playback and an auto-off timer.  Customisation = swap helmets.

The "Studio" + "mscript" naming in our codebase is ours — not
Dasai's.  We're not cloning a product, we're building one informed
by what works in the category.

We also already SHIP more content than the real product (167 vs
70+).  The renderer is category-competitive.  **What's missing is
the operator surface.**

## What works in the category (and what we'll borrow)

From EMO, Anki Vector, Eilik, Divoom Times Gate, VTube Studio,
Shimeji desktop pets:

| Pattern | Source | How we adopt |
|---|---|---|
| Thumbnail grid picker (hover-plays) | VTube Studio Expressions | Replaces our typed mode-name entry |
| Mood/scene wheel as home screen | EMO + Eilik modes | New top-level surface |
| Trigger bindings table (source → asset) | VTube Studio hotkeys | New Settings panel, drives our ZMQ bus |
| Idle vs reactive split | Mochi3 + Vector + EMO | Two render channels: looping idle + interrupt reactions |
| Reaction button row | Eilik touch zones | 6 large buttons across the bottom (Happy / Surprised / Sleepy / Wave / Dance / Stop) |
| Favorites / pinned tray | Divoom + macOS Dock | 6-8 user-pinned tiles, one click away |
| Scheduled scenes ("showtimes") | Eilik Festivals + Vector time-of-day | Cron-style scene scheduler |
| Personality slider (Calm ↔ Hyper) | Vector + EMO personality | Hides cadence + reaction-probability knobs behind a metaphor |
| Compact frameless "mini" window | Shimeji + desktop pets | The TOY surface is small + always-on-top; the configurator is the full window |
| Tray icon + right-click quick menu | Shimeji + EMO companion | Summon / Dismiss / Switch Scene / Mute / Open |

## What's wrong with the current operator surface

`gui/mochi_gui.py` (619 lines, Tk) is a debug tool:

- Typed mode-name entry (you have to KNOW the exact string)
- Mscript dropdown (works — only because file system reads names)
- Color picker, matrix-size knob, raw command box (renderer
  parameters, not toy controls)
- "Launch Virtual Display / Perf Monitor / Sprite Editor" buttons
  (developer ergonomics, not operator ergonomics)

It works.  Operators can manually trigger animations from it.  But
the cognitive load of remembering 167 names is unworkable, and the
interface signals "engineering preview," not "product."

There are also 5 other GUIs in `gui/` doing overlapping things
(`mochi_vdisplay.py`, `mochi_vdisplay_player.py`,
`mochi_vdisplay_player_qt.py`, `llm_chat_gui.py`, `mochi_perf.py`)
and 4 in `tools/` (`mochi_studio.py`, `bitmap_editor_gui.py`,
`sprite_editor_gui.py`, `mscript_editor_gui.py`).  Some are content
editors (keep), some are renderer viewers (consolidate), and one
is the LLM chat (move under the LLM optional module).

## The target product

### Three surfaces, distinct purposes

1. **The toy** — a frameless ~300px window showing just the
   character.  Always on top.  No chrome.  This is what an end
   user looks at all day.  Mirrors Shimeji.

2. **The companion app** — a full Qt window for browsing
   animations, picking scenes, binding triggers, scheduling
   showtimes, tuning personality.  This is what the operator
   opens to CONFIGURE the toy.  Mirrors EMO's mobile app +
   VTube Studio's main UI.

3. **The dev tools** — content editors (sprite / bitmap / mscript
   editors) + the perf monitor.  Already in `tools/`.  Keep, no
   redesign needed.

### Companion app layout (the headline new work)

```
┌─ Mochi ──────────────────────────────────── [_□×] ─┐
│                                                     │
│  ┌─ SCENE WHEEL ─────────────┐  ┌─ MINI PREVIEW ─┐ │
│  │  Chill   Hype             │  │                 │ │
│  │     │   │                  │  │  [character     │ │
│  │ Focus ─⊙─ Party            │  │   rendering at  │ │
│  │     │   │                  │  │   small size]    │ │
│  │  Sleepy  Drive             │  │                 │ │
│  └───────────────────────────┘  └─────────────────┘ │
│                                                     │
│  ┌─ FAVORITES ─────────────────────────────────────┐│
│  │  [happy]  [sleepy]  [wave]  [bow]  [stop]       ││
│  └─────────────────────────────────────────────────┘│
│                                                     │
│  ┌─ ANIMATION GRID ────────────────────────────────┐│
│  │  [Happy ▾] [Type: any ▾] [Search: _________]    ││
│  │  ╔══╗ ╔══╗ ╔══╗ ╔══╗ ╔══╗ ╔══╗                  ││
│  │  ║  ║ ║  ║ ║  ║ ║  ║ ║  ║ ║  ║   (scrolls)     ││
│  │  ╚══╝ ╚══╝ ╚══╝ ╚══╝ ╚══╝ ╚══╝                  ││
│  └─────────────────────────────────────────────────┘│
│                                                     │
│  [HAPPY] [SURPRISED] [SLEEPY] [WAVE] [DANCE] [STOP]│
│                                                     │
│  Personality:  Calm ━━━━●━━━━━━━ Hyper             │
│                                                     │
│  Tabs:  [ Home ] Scenes  Triggers  Schedule  Library│
└─────────────────────────────────────────────────────┘
```

Six surfaces under that companion-app frame:

| Tab | What it shows |
|---|---|
| **Home** | Scene wheel + favorites + animation grid + reaction button row + personality slider (the screenshot above) |
| **Scenes** | List of scenes (Chill / Hype / Focus / Sleepy / Party / Drive / Pomodoro / Festival), each one editable as a bundle of idle pool + reaction pool + triggers + audio |
| **Triggers** | Bindings table — rows of `Source → Asset`.  Sources include ZMQ topics, timer (every N min), time-of-day, system events (file change, MQTT, weather) |
| **Schedule** | Cron-style "showtimes": e.g. weekday 9-12 → Focus, Friday 5pm → Party, 11pm-7am → Sleep |
| **Library** | All 167 animations with metadata editor (mood / tags / hint) — operator curation surface for `CATALOG_OVERRIDES.yaml` |
| **Advanced** | Hidden by default — exposes color picker, matrix-size knob, raw command, log viewer (the existing debug controls, demoted) |

## The build plan

### Phase A — foundation (3-5 sessions)

The minimum that makes Mochi feel like a product.

| # | Item | Effort |
|---|---|---|
| A.1 | **Qt companion app skeleton** (`gui/mochi_companion.py`) — single Qt window, tabbed layout, no functionality yet | ~2 hrs |
| A.2 | **Animation grid picker** — reads `CATALOG.json`, shows thumbnails (or generated previews) grouped by mood, click → fires `mode <name>` | ~4 hrs |
| A.3 | **Mini window** (`gui/mochi_mini.py`) — frameless ~300px window subscribing to `node.animation.frame`, always-on-top | ~2 hrs |
| A.4 | **Reaction button row** — 6 big buttons at the bottom of the companion app, each bound to one operator-pinned animation, click → fires immediately | ~1 hr |
| A.5 | **Favorites tray** — operator drags assets from grid to favorites; favorites persist to `favorites.json` | ~2 hrs |
| A.6 | **Idle pool config** — operator picks 3-10 idle animations; renderer rotates through them | ~2 hrs (plus animation node change for the rotation behaviour) |

Ship target: a window the operator can open, browse, pin, click, and watch Mochi react in a small mini window.

### Phase B — scenes + scheduling (2-3 sessions)

The "this is a curated experience" upgrade.

| # | Item | Effort |
|---|---|---|
| B.1 | **Scene wheel home tab** | ~3 hrs |
| B.2 | **Scene definition format** — YAML files in `assets/scenes/`: `idle_pool`, `reaction_pool`, `default_mood`, `tempo_modifier` | ~1 hr |
| B.3 | **Scene loader on animation node** — switching scene reconfigures idle pool + reactive pool | ~2 hrs |
| B.4 | **Schedule tab** — cron-style scene scheduler with simple UI | ~3 hrs |
| B.5 | **Personality slider** — single dial that modulates idle cadence + reaction probability | ~2 hrs |

### Phase C — triggers + integration (2-3 sessions)

The "extensible" tier.

| # | Item | Effort |
|---|---|---|
| C.1 | **Triggers tab** — bindings table for `Source → Asset` | ~4 hrs |
| C.2 | **Trigger sources** — ZMQ topics (existing), wall-clock timer, time-of-day (existing infra), file watcher, MQTT subscriber | ~3 hrs |
| C.3 | **Tray icon + quick menu** — Summon / Dismiss / Switch Scene / Mute / Open Companion | ~2 hrs |
| C.4 | **Hardware key bindings** — Stream Deck / numpad / global hotkey to fire reactions | ~3 hrs |

### Phase D — content curation (1-2 sessions)

| # | Item | Effort |
|---|---|---|
| D.1 | **`CATALOG_OVERRIDES.yaml`** — operator-edited mood/tags/hint for the 137 "neutral" entries | ~1 session of UI-driven curation |
| D.2 | **Library tab** — in-app curation UI that writes to the overrides file | ~2 hrs |
| D.3 | **Default character pack** — pick the top 20-30 animations to be Mochi's default vocabulary; hide the rest behind a "show all" toggle | ~1 session |

### Phase E — LLM as optional module (already done)

The LLM track shipped at N→N+2 stays parked here.  When the
operator wants AI mode, the companion app gets a toggle.  No new
work needed — already wired.

## What we'd delete + consolidate

- `gui/mochi_vdisplay.py` + `mochi_vdisplay_player.py` +
  `mochi_vdisplay_player_qt.py` → consolidate into a single
  `gui/mochi_mini.py` (Phase A.3 replaces them all)
- `gui/llm_chat_gui.py` → moves to optional LLM module surface
- `tools/mochi_studio.py` (620 lines) → audit + decide.  Likely
  splits into content editor + library curator.
- `gui/mochi_gui.py` (619 lines) → demoted to `Advanced` tab inside
  the new companion app (its existing controls become the dev
  surface)
- `tools/control_cli.py` → kept (CLI is useful)
- `tools/bitmap_editor_gui.py`, `sprite_editor_gui.py`,
  `mscript_editor_gui.py` → kept as content authoring tools

## What we'd ship FIRST

**Phase A.1 + A.2 + A.3** — the Qt companion app skeleton + the
animation grid picker + the mini window.  All three together is
the smallest viable product surface: operator opens the companion,
browses with thumbnails, clicks, watches the mini window respond.

Estimated: one focused session (~6-8 hrs).

Everything else builds on these three.

## Open questions for the operator

1. **Companion-app primary aesthetic**: dark + glassmorphic (EMO),
   playful + colour (Eilik), minimal monochrome (Shimeji), or
   something else?
2. **Default character pack identity**: pick a "primary face" from
   the current 167 (suggest: the lilith-face / mochi-style chibi
   from the JROS work we did), or keep it generic?
3. **Trigger surface scope**: just ZMQ topics + time-of-day for
   v1, or include MQTT/file-watcher/hardware-key from day one?
4. **Scene defaults**: do you want me to author 6-8 starter scenes
   from the existing 167 assets, or wait for your curation pass?
5. **Mini-window-only mode**: should `python main.py --mini` skip
   the companion app entirely (just show the toy)?  Probably yes.

## References

- `https://dasai.com.au/pages/mochi3` (Dasai Mochi3 product page)
- VTube Studio: https://github.com/DenchiSoft/VTubeStudio/wiki
- EMO (Living.AI): https://living.ai/emo/
- Anki Vector TRM: https://randym32.github.io/Vector-TRM.pdf
- Eilik: https://energizelab.com/consumerview/eilik
- Divoom Times Gate: https://divoom.com/products/time-gate


---

## Operator decisions (2026-06-10)

### 1. Aesthetic — Wondershare style

Operator-selected reference: **Wondershare UniConverter** (screenshot
in chat history).  Specific elements to copy:

- **Left sidebar navigation** — vertical list of top-level
  surfaces (Home / Library / Scenes / Triggers / Schedule /
  Editors / Settings).  Icon + label per row.
- **Top tab strip** — category filter inside each page
  (Recently / Hot / Video / Audio / Image in Wondershare;
  for us: All / Happy / Sad / Angry / Sleepy / etc.)
- **Search bar top-right** — instant filter by name + tags
- **Card grid** — each card is preview image + bold title +
  subtitle + optional badge (New / 4K / AI / custom).  Lots of
  whitespace between cards.
- **White base + accent colour + dark text** — light theme,
  premium feel.  Wondershare's accent is purple; ours can be
  a soft Mochi-pink or stay purple for consistency.
- **Bottom-of-sidebar promo block** — Wondershare uses for
  upgrade nudge; we can use for "Mochi tip of the day" or scene
  shortcut.

Why this matches the project:
- "Very clean, very flexible, very reusable for other projects"
  (operator's words).  The style applies to JROS's eventual Swift
  operator console too.
- The companion app becomes our design-system reference for
  future work.

### 2. Pop-out floating window — confirmed + extended

Keep the existing `mochi_vdisplay_player_qt.py` concept (frameless
window subscribing to frame stream).  But formalise the body-skin
system the operator was already experimenting with:

- Body skins live at `assets/skins/<name>/`
- Each skin contains:
    - `frame.png` — the bezel/body image (e.g. `tv1.png`)
    - `meta.yaml` — screen bounding box (where the animation
      paints inside the bezel), default opacity, draggable
      regions, attribution
- Companion app has a **Skin picker** (in Settings) — preview each
  skin, set the active one
- `--mini` boot mode renders only the skinned floating window
  (no companion chrome)

Existing `assets/video/player/tv1.png` becomes the first skin
example.

### Remaining open questions (deferred — operator can answer mid-build)

  - Default character pack: pick one from existing 167 vs. design
    fresh
  - Trigger sources scope for v1: ZMQ + time only, or include
    MQTT/file-watch/hotkey from day one
  - Starter scenes: I author 6-8 from existing assets vs. wait for
    operator curation
