# Static images (png / bmp / icons)

## What it is

A single image, no time axis.  The simplest possible "animation"
— so simple it isn't really animation at all.  Useful as a
baseline for what every other technique adds.

## History

Photography (1820s) → bitmap displays (1970s) → web image formats
(GIF87a 1987, JPEG 1992, PNG 1996, WebP 2010).  Mochi uses PNG
for static frames and BMP for raw bitmaps (legacy / educational).

## How it works

Read pixels from a file → push them to the display.  Once.  Done.
No timing, no playback engine, no state machine.  Pillow's
`Image.open()` returns a single frame; you draw it.

## How Mochi implements it

- `nodes/animation/animations/image_handler.py` — PNG / static
  raster adapter
- `nodes/animation/animations/decoders/image_decoder.py` — wraps
  Pillow's loader
- Both reuse `media_base.py`'s `MediaFrames` with a length-1 list

## Try it

In the Library, set `TYPE: png` or `TYPE: icons` — 6 + 4 entries
respectively.  Click one; it appears in the mini window and
stays.  Compare with `TYPE: gifs` to feel the difference between
"image" and "animation."
