# Learn — animation, from cave painting to LED matrix

Mochi is a small project but the techniques it uses span the entire
history of moving images.  This series is the operator's teaching
material — when you're explaining animation to someone, the Learn
tab in the companion app pulls these chapters up alongside live
examples from the catalog.

## How this section is organised

Each chapter covers one **type** of animation that Mochi can
render.  Every chapter has the same five sections so you can
compare techniques apples-to-apples:

1. **What it is** — one sentence + the core idea.
2. **History** — where it came from, what it replaced, what
   replaced it.
3. **How it works** — the actual mechanism.  No hand-waving.
4. **How Mochi implements it** — the file in `nodes/animation/`
   that owns this type + what its adapter does.
5. **Try it** — one click filters the Library to this type so the
   operator can demonstrate live.

## Chapters

| # | Chapter | What it teaches |
|---|---|---|
| 01 | [Static images (png/bmp/icons)](static_images.md) | The simplest case: one frame, no time axis.  Where animation starts. |
| 02 | [Bitmaps (1-bit packed)](bitmaps.md) | Memory-efficient binary frames — how the earliest displays cheated. |
| 03 | [GIF / animated raster](gifs.md) | The format that taught the web how to move. |
| 04 | [Sprite sheets](sprites.md) | One image, many frames, picked by index.  The video-game backbone. |
| 05 | [Video clips](video.md) | Encoded streams — what happens when frame counts get too big for sheets. |
| 06 | [Procedural / math animations](math.md) | Code IS the animation.  No frames stored at all. |
| 07 | [Eye / state animations (declarative)](animations.md) | Keyframe definitions in JSON — how Mochi describes simple expressions. |
| 08 | [MochiScript (mscripts)](mscripts.md) | Mochi's scripting DSL — when you need timeline + branching + triggers. |

## How the categories fit together

It's tempting to think of these as a one-dimensional spectrum
("simple → complex" or "static → animated").  In practice they
sit on a 2-axis grid:

```
                     stored frames                    code-generated
                  ◄───────────────────────────────────────────────►
        static    [static_images]                     [math (still)]
           │
           ▼
       animated   [bitmaps, gifs, sprites,            [math (animated)]
                   video, animations(json)]            [mscripts]
```

The "stored frames" axis is what most people picture when they
hear "animation" — you make N pictures and play them back in
order.  The "code-generated" axis is the procedural alternative —
you write equations that produce a picture for time T.

The fun part: Mochi's renderer doesn't care which you use.  Drop
a GIF and a Python procedural script and they coexist in the
catalog, in the Library, and in the bus topic flow.  That's the
educational payoff: animation is not one thing.  It's a set of
related techniques solving the same problem (move pixels over
time) under different constraints (memory, CPU, art skill,
authorship time).

## System map

When you're explaining Mochi end-to-end, this is the path a
frame takes:

```
  ┌────────────────────────┐
  │ assets/CATALOG.json    │  ← what's available (built by
  └──────────┬─────────────┘    tools/build_catalog.py)
             │
             ▼
  ┌────────────────────────┐
  │ Companion app          │  ← Library / Packs / Settings UI
  │   gui/mochi_companion.py
  └──────────┬─────────────┘
             │  PUSH "mode <name>" or "play <path>"
             ▼
  ┌────────────────────────┐
  │ Animation node         │  ← creates the right Animation
  │   nodes/animation/node.py    object via animations/__init__.py
  └──────────┬─────────────┘
             │  every frame: render_into(buf)
             ▼
  ┌────────────────────────┐
  │ ZeroMQ broker          │  ← XPUB/XSUB proxy at :5555/:5557
  │   transport/broker.py        publishes ``node.animation.frame``
  └──────────┬─────────────┘
             │
             ▼
  ┌────────────────────────┐
  │ Mini window            │  ← frameless overlay, paints
  │   gui/mochi_vdisplay_player_qt.py  inside the skin's screen_bbox
  └────────────────────────┘
```

The companion + the mini window are two ends of the same bus.
Everything else is either content (`assets/`), config
(`config.yaml`), or the three-tier reorg (`agent/` / `nodes/` /
`transport/` / `core/`).

## When to use which type

A quick decision table — useful when authoring new content:

| Need | Best pick | Why |
|---|---|---|
| One static face/icon | **PNG** or **bitmap** | Simplest, no time math. |
| Short loop, hand-drawn | **GIF** | Industry standard, every editor exports it. |
| Many actions for one character | **Sprite sheet** | One image, many frames, cheap to load. |
| Long playback, real video | **Video** | When frame count makes sprite sheets absurd. |
| Geometric / parametric / generative | **Math** | No art skill needed; algorithm IS the art. |
| Simple expression with discrete states | **Animations (JSON)** | Declarative — happy/sad as data, not as drawing. |
| Multi-step performance with timing | **MochiScript** | When other types need to be sequenced. |
