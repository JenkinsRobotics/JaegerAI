# Asset properties (sidecar `.props.yaml` files)

**Status:** convention defined — first generator + reader landed
with this commit.  Operator extends per-asset properties over time.
**Scope:** how each animation gets its own metadata file for
filtering, playback tuning, and type-specific derived data
(sprite-sheet sub-image coordinates, math parameters, etc.).

## Operator brief (2026-06-10)

> *each animation should have some type of properties file or
> data — ideal size, playback speed, framing, etc... so we can
> implement filtering.  Stuff like sprites can be generated since
> it stores the location of the sprite, the sub-images are, etc.*

## The convention

Every animation file may have a sibling `.props.yaml` file with
the same basename:

```
assets/gifs/happy.gif
assets/gifs/happy.props.yaml      ← sidecar

assets/math/rainbow.py
assets/math/rainbow.props.yaml    ← sidecar

assets/png/sprite_sheet_a.png
assets/png/sprite_sheet_a.props.yaml ← sidecar (with sprite grid)
```

Sidecars are **OPTIONAL**.  When absent, the catalog uses sensible
defaults derived from the file itself (dimensions from Pillow,
type from extension, mood guessed from filename).  When present,
the sidecar's fields take precedence — operator-authored truth
overrides auto-detection.

## Common fields (any animation type)

```yaml
schema: asset-props/v1

# Display name (defaults to filename stem).
name: "Happy Blink"

# Authoring credit / source.
author: "Mochi project"
license: "MIT"
source_url: ""

# Curation metadata — overrides what build_catalog.py auto-guesses.
mood: happy
tags: [eyes, blink, happy, expressive]
hint: "Quick happy eye blink — use for short positive reactions"

# Rendering hints.
ideal_size: [64, 64]           # target display size [w, h]
framing: fit                   # fit | fill | center | stretch
playback_speed: 1.0            # 1.0 = native; 2.0 = double speed
loop: true                     # auto-restart at end
duration_ms: null              # override for one-shot (auto-stop)

# Operator notes / safety flags.
notes: ""
nsfw: false
```

## Type-specific fields

### GIFs

```yaml
type_props:
  fps: 24                      # override decoded delays
  start_frame: 0
  end_frame: null              # null = end of file
  bg_color: [0, 0, 0]          # behind transparent pixels
```

### Sprites (sheets)

This is the case the operator called out specifically.  A sprite
sheet packs N frames into one image; the sidecar declares the
grid so the renderer can crop the right cell each frame:

```yaml
type_props:
  frame_size: [64, 64]         # [w, h] of each cell
  frame_count: 12              # total cells
  grid: [4, 3]                 # [cols, rows] in the sheet
  frame_rate_ms: 100           # ms per frame
  pivot: [32, 32]              # rotation/anchor point inside cell
  named_frames:                # optional: name → cell index
    idle:    0
    walk_1:  1
    walk_2:  2
    jump:    3
    fall:    4
```

With named_frames the renderer can fire `mode sheet_a:walk_1`
directly — the slot-style addressing used for packs in
[`docs/PACK_CONVENTION.md`](PACK_CONVENTION.md).

### Math (procedural)

```yaml
type_props:
  entry: "frame"               # function name in the script
                                # default: 'render' or 'frame'
  period_s: 2.0                # one cycle length (for loop awareness)
  params:                      # default values for the script
    speed:     0.05
    palette:   "rainbow"
    intensity: 1.0
  param_schema:                # what the operator can tune live
    speed:     {type: float, min: 0.01, max: 0.5, step: 0.01}
    intensity: {type: float, min: 0.0,  max: 2.0,  step: 0.1}
```

This is where math animations get expressive: a sidecar declares
which parameters the operator can sweep live, and what their
valid ranges are.  The companion app (Library detail view, when
built) shows sliders for each declared param.

### Video

```yaml
type_props:
  fps: 24
  start_s: 0.0                 # trim front
  end_s: null                  # trim back; null = end of file
  audio: false                 # play audio on the host?
```

### Animations (declarative JSON eye anims)

```yaml
type_props:
  blink_interval_ms: 3500      # how often the auto-blink fires
  pupil_color: [255, 255, 255]
  bg_color:    [0, 0, 0]
```

### MochiScripts

```yaml
type_props:
  expects_modes: [solid_color, happy_blink]   # other modes referenced
  expected_duration_s: 4.2
  loop: false
```

## How sidecars are consumed

### `tools/build_catalog.py`

Reads every renderable asset.  When a sibling `.props.yaml` exists,
its fields are merged into the catalog entry (sidecar wins over
auto-derived).  Catalog grows fields like `ideal_size`,
`playback_speed`, `framing`, `type_props.*`.

### Companion app

The Library page can now filter on these fields (additional
chip rows for "Size", "Loop", "Has named frames", etc.) once the
operator populates them.  Sprite sheets with `named_frames` get a
flyout in the Library card showing each frame as a clickable
sub-cell.

### Animation node

`gif_handler`, `sprite_handler`, `math_handler`, etc. read the
sidecar at load time and respect:
- `playback_speed` — multiplies the timer increment
- `framing` — chooses the resize / paint strategy
- `type_props.*` — feeds the per-type adapter (sprite grid, math
  params, etc.)

## Authoring workflow

1. Pick an asset, e.g. `assets/gifs/happy.gif`
2. Drop a sidecar next to it: `assets/gifs/happy.props.yaml`
3. Fill in the fields above (only the ones that matter for that
   asset — everything is optional)
4. Run `python tools/build_catalog.py` — sidecar gets merged into
   `CATALOG.json`
5. Reload the companion app — filters / metadata reflect the
   sidecar

## Bulk authoring

For starting from scratch, `tools/scaffold_props.py` (shipping
with this commit) walks `assets/` and writes a stub `.props.yaml`
next to every asset that doesn't have one yet.  Stubs contain
auto-derived defaults the operator then refines manually.

```bash
# preview without writing
python tools/scaffold_props.py --dry-run

# write stubs for all assets that don't have one
python tools/scaffold_props.py

# write stubs only for sprite-sheet candidates
python tools/scaffold_props.py --filter sprites
```

## Out of scope (for now)

- A GUI sidecar editor — defer until the operator has authored
  enough sidecars to know which fields matter most
- Auto-population from EXIF / file metadata — easy follow-up
- Per-skin overrides (some skin's screen is smaller, ideal_size
  should adjust) — covered by the skin's `meta.yaml` instead
- Per-frame metadata for video clips (chapter markers etc.) —
  scope creep; revisit when needed
