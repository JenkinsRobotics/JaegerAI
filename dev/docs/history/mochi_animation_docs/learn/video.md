# Video clips

## What it is

A video file (mp4 / webm / mov) decoded frame-by-frame and
painted to the display.  For when frame counts exceed what
sprite sheets or GIFs can practically hold.

## History

- **1929** — first sound film with synchronised audio (*Blackmail*,
  Hitchcock).  Set the "video = lots of frames + timing" template
  digitally still uses.
- **1990s** — MPEG-1 / MPEG-2 codecs make digital video tractable
  on consumer hardware
- **2000s** — H.264 dominates; YouTube launches (2005); video
  becomes universally cheap
- **2010s** — VP9 + AV1 chase H.264; mobile encoders make capture
  free
- **Now** — Mochi can play video at 64×64.  Strange?  Yes.  But
  the renderer doesn't care about resolution.

## How it works

Each video frame is decoded by FFmpeg/imageio into an RGB array;
the array is downsampled to the renderer's logical size; the
buffer is painted.  Per-frame timing comes from the container's
timebase, not our renderer.

## How Mochi implements it

- `nodes/animation/animations/video_handler.py` — video adapter
- `nodes/animation/animations/decoders/video_decoder.py` — uses
  imageio (which wraps FFmpeg)
- `assets/video/` — 31 source clips, mostly Mochi-style faces
  hand-animated + exported

## Try it

In the Library, set `TYPE: video` — 31 entries.  These are the
most "art-heavy" assets in the project.  Worth comparing one to
its GIF equivalent: same content, very different file size +
playback path.
