# Mochi demo audit (operator's animation engine, vendoring-source for 0.5)

**Date:** 2026-06-08
**Source:** `/Users/jonathanjenkins/GITHUB/Mochi/`
**License:** Apache 2.0 (compatible with JROS's Apache 2.0 — vendoring OK)
**Why this audit:** Mochi is the operator's prior animation work.  The
plan for 0.5 is to bring its `animation_node` into JROS as the
foundation for the avatar / face / animation layer, evolving it with
JROS conventions (msgspec topics, the new skill-tree levels pattern,
Swift renderer).

## Mochi's architecture in one diagram

```
┌──────────────────────────────────────────────────────────┐
│  AnimationNode (Mochi)                                    │
│  - loads config + asset paths                             │
│  - subscribes to ZMQ commands                            │
│  - holds current Animation instance                       │
│  - per-frame: animation.render_into(t, pixel_buf)        │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  Animation (ABC)       │
         │  + render_into(t, buf) │  ← every adapter implements this
         │  + on_enter(**kw)      │
         │  + on_event(name, **kw)│
         │  + set_size(w, h)      │
         └───────────┬───────────┘
                     │
       ┌─────────────┼─────────────┬──────────┬──────────┐
       │             │             │          │          │
       ▼             ▼             ▼          ▼          ▼
   ImageHandler  GifHandler   VideoHandler  BitmapH.  SpriteH.   MathHandler
   (L1 static)   (L3 gif)     (L4 mp4)      (L1)      (L2)       (L4 math/py)
                                                                  ↑
                                                  procedural / code-defined
```

## Components — keep / vendor / evolve / drop

### KEEP as reference (read-only — operator's prior art)

* `/Users/jonathanjenkins/GITHUB/Mochi/` stays in the workspace.  The
  Mscript engine + GUI players + sample assets are reference
  material.  We don't redistribute them as part of JROS.

### VENDOR into JROS at `jaeger_os/nodes/animation/`

These get copied with Apache-2.0 attribution preserved in file
headers and adapted to JROS conventions (msgspec topics, runtime
singleton, skill-tree levels).

| Mochi file | JROS target | Notes |
|---|---|---|
| `plugins/animation_node/plugin_core/mochi_animations.py` (`Animation` ABC, `Command` NamedTuple) | `jaeger_os/nodes/animation/base.py` | The Protocol.  `Command` becomes a msgspec.Struct. |
| `plugins/animation_node/animations/media_base.py` | `jaeger_os/nodes/animation/adapters/media_base.py` | Frame-based animation helper.  Renamed `DecodedMediaAnimation` → `MediaAnimationAdapter`. |
| `animations/image_handler.py` | `adapters/image_adapter.py` | **L1 — static image** |
| `animations/bitmap_handler.py` | `adapters/bitmap_adapter.py` | **L1 — bitmap font / pixel** |
| `animations/sprite_handler.py` | `adapters/sprite_adapter.py` | **L2 — sprite sheet** |
| `animations/gif_handler.py` | `adapters/gif_adapter.py` | **L3 — looping GIF/APNG** |
| `animations/video_handler.py` | `adapters/video_adapter.py` | **L4 — mp4 / webm video** |
| `animations/math_handler.py` | `adapters/math_adapter.py` | **L4 — math/procedural Python script** |
| `animations/media_handler.py` | `adapters/media_adapter.py` | Polymorphic media wrapper |
| `animations/decoders/` | `adapters/decoders/` | Pillow / cv2 decoders |
| `plugin_core/gfx.py` | `jaeger_os/nodes/animation/gfx.py` | Pixel-buffer helpers (clear, blit, alpha) |
| `plugin_core/font.py` | `jaeger_os/nodes/animation/font.py` | Bitmap font rendering |
| `plugin_core/color_utils.py` | `jaeger_os/nodes/animation/color.py` | Hex → RGB, palette ops |
| `plugin_core/node_state.py` | merged into `jaeger_os/nodes/animation/state.py` | Active-animation tracking |

### EVOLVE — reshape to JROS conventions

| Mochi piece | JROS replacement |
|---|---|
| ZMQ command socket | `/act/animation` + `/act/timeline` bus topics (msgspec.Struct) |
| `Command(NamedTuple)` | `AnimationCommand(TopicMessage)` msgspec.Struct |
| `plugin_core/mscript_engine.py` | `jaeger_os/timeline/` module with OTIO-inspired multi-track Timeline schema; mscript files COMPILE to Timeline at load time (back-compat for one release) |
| `MochiNodeBase` | already exists — `jaeger_os.nodes.base.Node` |
| Qt-based player (`mochi_vdisplay_player_qt.py`, etc.) | **Swift renderer at `apps/JROS-Avatar/`** (operator pivot — Mac-native).  Python AnimationNode renders pixel buffers, ships them to Swift over WebSocket; Swift displays. |

### DROP entirely

| Mochi piece | Why |
|---|---|
| `mscript_editor_gui.py` | Tkinter editor for mscript; mscript is no longer the authored format |
| `gui/llm_chat_gui.py` | JROS has its own TUI; no LLM UI needed in animation surface |
| `gui/mochi_gui.py`, `gui/mochi_perf.py` | Operator dashboards specific to Mochi's standalone use; JROS uses its own runtime + bench |
| `core/node_base.py` (Mochi's) | JROS Node base is the system of record |
| `core/zmq_manager.py` (Mochi's) | JROS Bus replaces it |

## The 7 handler types → 6 animation levels (skill-tree mapping)

Mochi's handler set maps cleanly to the **animation skill tree**:

```
Level 1 — STATIC (works on any display)
  └─ ImageAdapter        (single raster image)
  └─ BitmapAdapter       (pixel-precise bitmap / font)

Level 2 — SPRITE (frame sequences, sheet-based)
  └─ SpriteAdapter       (sprite sheet, JSON-defined frames)

Level 3 — GIF (decoded GIF/APNG loops)
  └─ GifAdapter

Level 4 — VIDEO + PROCEDURAL
  └─ VideoAdapter        (mp4 / webm playback)
  └─ MathAdapter         (Python script renders procedurally)

Level 5 — RIGGED   ← NEW, not in Mochi
  └─ Live2DAdapter       (Cubism SDK, deferred)
  └─ SpineAdapter        (Esoteric Spine runtime, deferred)

Level 6 — GENERATIVE   ← NEW, not in Mochi
  └─ DiffusionAdapter    (Wan2.1 / SVD per-clip generation, deferred)
  └─ NeRFAdapter         (real-time NeRF, aspirational)
```

L5/L6 are ROADMAP only.  L1-L4 land in 0.5 as vendored Mochi handlers
re-wrapped for JROS.

## Mscript — interesting, archive as compiler input

```
[Main start]
MATH K[1] D[61.0] FG[255,0,0]
WAIT D[0.1]
MATH K[1] EVENT[start] DUR_M[1]
WAIT D[60.9]
[Main end]
```

* FANUC-style line-based scripting.  Useful precedent — robotics
  programming culture meets animation timing.
* But: linear, single-track, mechanical.  Operator confirmed mscript
  feels "limiting" for animation timing where multiple things happen
  in parallel.
* 0.5 plan: Mscript becomes a **one-way compiler input**.  Existing
  `.mscript` files load via a compile step that builds a Timeline
  (single track, sequential clips).  Authoring goes to the new
  multi-track Timeline schema (OTIO-inspired JSON).
* No new mscript files are authored; the editor is dropped.

## Assets — what to vendor vs. operator-supplied

Mochi ships with sample assets at `assets/`:
- `assets/animations/` — sprite + bitmap JSON definitions
- `assets/math/` — Python animation scripts (game-of-life, gfx, wave, timer)
- `assets/media/` — sample images, gifs, mp4s
- `assets/mscripts/` — mscript demos

**For 0.5 ship:**
- Sample animations move to `apps/JROS-Avatar/sample-assets/` so the
  shipping app has demonstration content out of the box.
- Operator's actual mochi-face assets (Lilith's face design, etc.)
  live per-instance at `<instance>/avatar/` — operator-owned.

## Skill-tree XP integration (the new bit, not in Mochi)

Each animation adapter is a SkillNode.  When it gets used:
- First play → unlock event ("Sprite adapter — first use")
- Per-play tick → XP accumulation
- Mastery thresholds → "Mastered" status, eligible to unlock L+1 adapter

Prerequisites graph:
```
image(L1) ─┬─→ bitmap(L1) ─→ sprite(L2) ─→ gif(L3) ─→ video(L4)
           └─→                              └─→ math(L4) ←─ sprite
```

Skill-tree foundation lives in `jaeger_os/skill_tree/` (designed
separately this session) — animation just registers its tree slice.

## Verdict

Mochi gives us a 70% head start on 0.5's animation work.  Architecture
is sound, license is compatible, the handler set IS the skill-tree
foundation we want.  What we add:

1. JROS bus + msgspec topics (replace ZMQ command socket)
2. Multi-track timeline runner (replace single-track mscript)
3. Swift renderer (replace Qt player)
4. Skill-tree XP integration (new layer on top)
5. L5 (rigged) + L6 (generative) adapter slots for future

Vendoring lands as the first commit of the animation track.  All
files carry "vendored from Mochi (Apache 2.0); see
dev/docs/library_review/mochi_demo.md for the audit" header.
