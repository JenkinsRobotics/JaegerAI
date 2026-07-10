# Bitmaps (1-bit packed)

## What it is

A bitmap with one bit per pixel — pixel is either on or off,
nothing in between.  Used historically because memory was
expensive: a 64×64 1-bit image is 512 bytes, vs 12,288 for
full RGB.

## History

- **1970s** — CRT displays, monochrome.  Bitmap was the only
  practical format.
- **1980s** — Mac OS used 1-bit bitmaps for icons + UI;
  GEM/Windows did the same.
- **2000s+** — LCD/OLED character displays (SSD1306, SH1106)
  bring 1-bit back for embedded systems.  Mochi3 hardware
  (Dasai) uses one.

## How it works

Each row of the image is packed into bytes — 8 pixels per byte.
Reading a row is a tight bit-shift loop.  Storage is 1/24th of
RGB888, which is why these formats persist in embedded contexts.

## How Mochi implements it

- `nodes/animation/animations/bitmap_handler.py` — bitmap mode
  adapter
- `assets/bitmaps/*.json` — Mochi's bitmap format: a 2D array
  of `0` / `1` ints + metadata
- The renderer expands to RGB at render time (operator can tint
  via `color` ctrl command)

## Try it

In the Library, set `TYPE: bitmaps` — 5 entries.  These are the
purest "old-school computer graphics" examples in the project.
The `color` ctrl command (`Color Control` in the legacy
mochi_gui) lets you re-tint them live, which is itself a teaching
moment: 1-bit doesn't mean monochrome — it means *one mask + one
colour*.
