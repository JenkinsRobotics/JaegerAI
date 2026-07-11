# Pack convention (2026-06-10)

**Status:** template — for the operator's pack authoring work.
**Scope:** how a character/style pack is laid out so the companion
app + animation node can use it without renaming files.

## Why packs

Operator note (2026-06-10):

> *similar to how video games have character animation packs...
> basically that's what we are doing*

A **pack** = one character / style with a curated set of emotion +
action clips that share its look.  Browse by pack first.  Pick the
pack, then pick the emotion.

The catalog (`assets/CATALOG.json`) keeps working for one-off clips
that aren't tied to a pack.  Both surfaces coexist.

## Folder layout

```
assets/
├── CATALOG.json                 ← flat one-off index (existing)
├── packs/
│   ├── PACKS.json               ← pack-keyed index (built by
│   │                              tools/build_pack_index.py)
│   ├── eye_default/             ← example: 6 eye JSONs as a pack
│   │   ├── pack.yaml            ← required: pack manifest
│   │   ├── preview.gif          ← optional: 1-2 second preview
│   │   │                          for the companion card thumb
│   │   ├── idle.json            ← emotion-slot files
│   │   ├── happy.json
│   │   ├── sad.json
│   │   ├── ...
│   │   └── README.md            ← optional: attribution / notes
│   │
│   └── chasm_daltyn/            ← future: assembled from existing
│       ├── pack.yaml              ChasmDaltyn*.gif files
│       ├── idle.gif
│       ├── attack.gif           ← reuses ChasmDaltynPunch.gif via symlink
│       └── ...
```

## `pack.yaml` schema

```yaml
schema: pack/v1
id: eye_default                    # filesystem-safe; must match folder name
name: "Default Eyes"               # display name for the companion
author: "Mochi project"            # operator / artist credit
license: "MIT"                     # short license tag
description: >-
  Six minimalist eye-only expressions ported from the legacy
  eye_animation JSON definitions.  Good baseline pack to demonstrate
  the slot system.

# What animation backend renders this pack.  Animation node uses this
# to pick the right adapter (one of: image, bitmap, sprite, gif,
# video, math, mscript).
default_adapter: animations

# Emotion / action slots the pack provides.  Each slot is a string
# key (operator picks the vocabulary per pack — there's no global
# fixed list).  Value is one of:
#
#   - a single filename (relative to the pack folder)
#   - a list of filenames (companion picks one at random per fire)
#   - a dict {file: ..., loop: true, fps: 24, ...} for per-slot tuning
slots:
  idle:     "neutral_blink.json"
  happy:    "happy_blink.json"
  sad:      "sad_blink.json"
  look_up:  "look_up.json"
  look_down:"look_down.json"
  sleeping: "closed.json"

# What slot fires when the pack is activated.  Required.
default_slot: idle

# Optional companion display hints.
preview_slot: happy              # which slot to use for the pack card thumbnail
tags: ["eyes", "minimalist", "default"]
```

## Slot vocabulary — operator-defined per pack

Different packs can have different emotion / action slots.  A face
pack might have `happy / sad / surprised`; a combat pack might have
`idle / attack / block / hurt / victory`.

The companion reads `slots` from each pack's `pack.yaml` and shows
exactly those.  No global fixed list to fight against.

Common slot keys worth standardising loosely (so reaction buttons
can be wired generically when possible):

```
   idle        looping ambient (required)
   happy       positive reaction
   sad         negative reaction
   angry       aggressive / frustrated
   sleepy      tired / dozing
   surprised   alert / shock
   thinking    contemplative / pondering
   wave        greeting / hello
   dance       celebration / energetic
   stop        deactivate / blank
```

A pack doesn't need to fill every slot.  Slots a pack doesn't
provide get an "(none)" placeholder in the companion's reaction
row, which becomes a no-op when clicked.

## How the companion uses it

1. **Packs page (sidebar item)** — top-level browse.  Shows one
   card per pack folder, sorted by name.  Card content:
   pack `name`, `description` excerpt, `preview_slot` thumbnail,
   slot count, license + author tags.

2. **Pack detail view** — click a card → emotion-slot view.  Shows
   each slot as its own mini-card with the asset preview.  Click
   a slot → fires `mode <pack_id>:<slot>` via the existing ctrl
   socket.

3. **"Set Active Pack" button** — designates which pack the
   reaction button row + LLM picker + auto-driver use by default.
   Stored in `assets/packs/active.txt` (single line, the pack id).

4. **Library page (one-offs, existing)** — unchanged.  Continues
   to browse `CATALOG.json` for non-pack clips.

## How the animation node uses it

When the operator fires `mode eye_default:happy`, the animation
node:

1. Looks up the pack `eye_default` in `assets/packs/PACKS.json`
2. Reads its `default_adapter` (`animations`) and the path for slot
   `happy` (`happy_blink.json`)
3. Routes through the existing `_process_node_command` path as if
   the operator had typed `mode happy_blink` directly

The slot syntax is sugar — the underlying renderer doesn't need to
know about packs.

## Operator authoring workflow

1. Create folder under `assets/packs/<id>/`
2. Drop animation files inside (or symlink existing ones)
3. Write `pack.yaml` with the slot map
4. Run `python tools/build_pack_index.py` to regenerate
   `assets/packs/PACKS.json`
5. Refresh the companion app — the pack appears on the Packs page

For the first pack, the eye-only one is the cleanest starter:

```bash
mkdir -p assets/packs/eye_default
# copy or symlink the 6 eye_animation JSONs
for f in closed happy_blink look_down look_up neutral_blink sad_blink; do
  ln -s ../../animations/$f.json assets/packs/eye_default/$f.json
done
# author pack.yaml using the schema above
```

## Out of scope here

- Pack marketplace / sharing format (zip with pack.yaml + assets
  — easy later)
- Multi-pack blending (mix face from pack A with body from pack B —
  defer to "skins" concept once first pack ships)
- Auto-pack-detection from filename prefixes (the prefix analysis
  found 9 plausible packs; if the operator wants those auto-bound,
  add `tools/auto_pack.py` — for now, manual authoring keeps things
  honest)
