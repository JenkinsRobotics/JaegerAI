# Skin convention (2026-06-10)

**Status:** in use — first skin (`tv1`) shipped with this commit.
**Scope:** how the mini window's body / bezel is packaged.

## What a skin is

A **skin** = a body image that wraps the animation render area.  The
TV bezel currently at `assets/video/player/tv1.png` is the prototype:
the renderer paints into a rectangular cutout inside the bezel's
alpha region.

Each skin is independently selectable from the companion app's
Settings page (when wired) or via the `--skin` CLI flag on the
mini-window launcher.

## Folder layout

```
assets/
└── skins/
    ├── tv1/
    │   ├── body.png         ← required: alpha-cutout body image
    │   ├── meta.yaml        ← required: screen_bbox + window defaults
    │   └── README.md        ← optional: attribution / notes
    │
    └── future_skin/
        ├── body.png
        ├── meta.yaml
        └── ...
```

`body.png` is required.  It MUST contain transparency where the
animation should appear (the screen cutout) and opaque pixels
elsewhere (the bezel/body artwork).  Non-PNG formats aren't
supported by the Qt overlay's per-pixel alpha path.

## `meta.yaml` schema

```yaml
schema: skin/v1
id: tv1                          # filesystem-safe; must match folder name
name: "TV 1"                     # display name for the companion picker
author: "Mochi project"          # operator / artist credit
license: "internal"              # short license tag
description: >-
  A retro CRT television bezel.  The screen cutout is a hand-trimmed
  alpha region in body.png; the animation renderer paints into the
  ``screen_bbox`` rectangle below.

# Where the renderer paints inside the body image.
# Coordinates are pixels in the body.png coordinate system:
#   [left, top, width, height]
screen_bbox: [425, 289, 150, 150]

# Window behaviour defaults — overridable per-launch by the companion
# or CLI flags.
topmost: true                    # always on top of other windows
drag: true                       # click anywhere to drag the window
opacity: 1.0                     # 0.0..1.0 (1.0 = fully opaque)
scale:   1.0                     # uniform scale multiplier
```

## Authoring a new skin

1. Create `assets/skins/<your_id>/`
2. Drop in `body.png` (alpha cutout where the screen should be)
3. Author `meta.yaml` — most important field is `screen_bbox`
   (find it with any image editor's ruler)
4. Restart the companion → new skin appears in the picker

## Why a new convention vs the existing `display_players` config

The existing `display_players:` block in `config.yaml` does
essentially the same thing, but conflates:
- skin metadata (image + screen bbox)
- runtime behaviour (sub address + poll interval)

The new `assets/skins/<id>/` shape separates them cleanly:
- skin = `body.png` + `meta.yaml` — portable, drop-in
- runtime = launcher CLI flags or companion settings

The existing `display_players:` config keeps working for now (the Qt
overlay reads it via `--profile`), but the new skin convention is the
operator-facing surface going forward.

## How the launcher uses a skin

```bash
# CLI launch (manual)
python gui/mochi_mini.py --skin assets/skins/tv1
```

The launcher:
1. Reads `meta.yaml`
2. Loads `body.png` into a frameless Qt window
3. Subscribes to the animation node's frame stream
4. Paints incoming frames into `screen_bbox`
5. Applies window flags (`topmost`, `drag`, `opacity`)

When the companion app's Settings page lands, picking a skin
persists the choice to `assets/skins/active.txt` (single-line skin
id) and the mini window re-launches with the new skin.

## Out of scope

- Animated body skins (operator's earlier "playing around with body
  design" — moving / glowing bezel art).  Adding `body_anim.gif` as
  an optional field is straightforward when needed.
- Multi-screen skins (two cutouts side by side).  Same — needs a
  list of `screen_bbox` entries.
- Skin sharing format (zip with body.png + meta.yaml — easy later).
