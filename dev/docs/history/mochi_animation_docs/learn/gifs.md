# GIFs & animated raster

## What it is

A **GIF** is a sequence of full-frame raster images packaged
together with per-frame timing, in a single file the browser /
viewer plays back automatically.  68 of Mochi's 167 assets are
GIFs — the largest single type.

The animation is "stored" — every frame is a real picture saved on
disk.  Contrast with procedural/math animation (chapter 06) where
the pictures don't exist until the renderer computes them.

## History

- **1987** — CompuServe releases GIF87a.  Single-frame only;
  animation isn't part of the spec yet.
- **1989** — GIF89a adds the Graphics Control Extension —
  per-frame `delay` and `disposal_method` fields.  Animation is
  born accidentally, as side-effect of "let me let you stack
  multiple images in one file."
- **1995-2005** — GIF dominates the web's animated era.  Every
  banner ad, every guestbook, every Geocities homepage.
- **2010s** — Twitter/Reddit start auto-converting uploaded GIFs
  to MP4 video on the backend because GIF is dramatically less
  efficient than modern video codecs.  The user-visible "GIF"
  becomes a brand, not a format.
- **2020s** — GIFs persist for short reaction loops where small
  size + universal autoplay > file efficiency.  Mochi uses them
  the same way: 1-2s expressive loops, no audio needed.

## How it works

Three layers:

1. **Palette per frame** — each frame can declare its own 256-colour
   palette (or share a global one).  This is why GIFs look "low-fi"
   — you're limited to 256 distinct colours per frame even if your
   source is 16M.

2. **Disposal method** — between frames, what happens to the
   previous one?  Options: "leave it" (overlay), "restore
   background" (cell-based), "restore previous" (sprite-like).
   Most GIFs use "leave it" + small per-frame patches, which is
   actually a primitive form of delta compression.

3. **LZW compression** — the actual pixel data is run-length
   encoded with a dictionary-based scheme.  Cheap to decode,
   ~2-4x compression typical.  Lossless.

So a GIF isn't "a video that loops."  It's more like "a sprite
sheet that includes its own playback engine."

## How Mochi implements it

| File | Role |
|---|---|
| `nodes/animation/animations/gif_handler.py` | Adapter that wraps a decoded GIF as an `Animation` |
| `nodes/animation/animations/decoders/gif_decoder.py` | Pillow-backed decoder; produces a list of frames + per-frame delays |
| `nodes/animation/animations/media_base.py` | Shared base for raster animations (GIF + video) — handles per-frame timing |
| `nodes/animation/animations/__init__.py` | Registers `gif` as a creatable mode by extension |

The flow when you click a GIF card in the Library:

1. Companion sends `node animation mode on <gif_name>` via PUSH
2. Animation node looks up `<gif_name>` in the catalog → finds the
   GIF path
3. `gif_decoder.decode_gif()` reads the file via Pillow, builds a
   `MediaFrames` object (list of frames + delays)
4. `gif_handler.GifAnimation` wraps that as an `Animation` with
   `render_into(timestamp, buf)`
5. Renderer paints the right frame for `timestamp` into the pixel
   buffer
6. Broker publishes the frame; the mini window draws it inside
   the skin's `screen_bbox`

## Try it

In the companion app's Library tab, set:

- **MOOD:** ALL
- **TYPE:** gifs

You'll see all 68 GIF entries.  Click any to fire it.  A good
teaching pair: `happy` (a hand-drawn GIF) and `RIVE_big_smile_animation`
(a Lottie-style export from a vector tool — same final format,
very different authoring pipeline).

## Where to dig deeper

- Pillow docs: `PIL.GifImagePlugin` — the actual decoder Mochi uses
- The original GIF89a spec
  ([w3.org/Graphics/GIF/spec-gif89a.txt](https://www.w3.org/Graphics/GIF/spec-gif89a.txt))
  is short and surprisingly readable
- Compare a GIF and the same content as an MP4 via
  `ffprobe` to see why modern video is so much smaller
