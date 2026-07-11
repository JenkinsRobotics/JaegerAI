# Sprite sheets

## What it is

One image containing many frames laid out in a grid; the renderer
picks the right cell per frame.  The video-game backbone since
arcade machines in the late 70s.

## History

- **1976** — Atari 2600's TIA chip introduces hardware sprite
  blitters.  Sprite = independently-positioned bitmap.
- **1980s** — NES / SNES / Mega Drive: full sprite sheets in
  ROM.  Mario walking is 3 frames repositioned in the sheet.
- **2000s** — Flash + HTML5 Canvas — sprite sheets dominate web
  games.  Tools like Aseprite + TexturePacker formalise the
  workflow.
- **Now** — same idea, smaller targets.  Mochi's 64×64 LED grid
  is conceptually identical to a 1980s arcade screen.

## How it works

1. Author packs N frames into a single image (`sprite.png`)
2. A metadata file (JSON or sidecar) declares frame size + count
3. At runtime, frame `i` is the rectangle
   `(i*w % sheet_w, (i*w // sheet_w)*h, w, h)`
4. The renderer crops that rectangle each frame

Trade-off: one disk read for the whole animation (fast loading),
at the cost of needing the metadata to be right.

## How Mochi implements it

- `nodes/animation/animations/sprite_handler.py` — sprite-sheet
  adapter
- Sheet image lives in `assets/png/` (or wherever); the
  `sprite.json` next to it declares `frame_w` + `frame_h` +
  `frame_count`
- Frame-rate is set per-sprite, not globally

## Try it

Currently most of Mochi's catalog uses GIF where games would have
used sprites.  Authoring a sprite-sheet character pack (per the
operator's pack work) is one of the most accessible first
contributions — see `tools/sprite_editor_gui.py` for an in-tree
authoring tool.
