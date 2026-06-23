#!/usr/bin/env python3
"""Render an animated GIF of Lilith cycling through every emotion +
breathing + blinking + lip-syncing.  Opens the GIF in the default
viewer when done.

Usage:
    ./dev/scripts/lilith_demo.py
    .venv/bin/python dev/scripts/lilith_demo.py

Output:
    /tmp/lilith_demo.gif (overwritten each run)

Cycle:
    Each emotion plays for ~2 s; "speaking" plays for ~3 s with
    sin-wave amplitude driving the mouth.  Total runtime ~16 s.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from jaeger_os.nodes.animation.adapters import MathAdapter


FACE_SCRIPT = (
    REPO / "jaeger_os" / "agent" / "personas" / "lilith"
    / "avatar" / "faces" / "lilith_face.py"
)

OUT_GIF = Path("/tmp/lilith_demo.gif")
# Lilith renders NATIVELY at 64x64 (LED matrix target).  We
# nearest-neighbor upscale for viewing so the pixel art reads
# crisp on a regular Mac screen.
NATIVE = 64
SCALE = 8
WIDTH, HEIGHT = NATIVE, NATIVE
FPS = 24


EMOTIONS = [
    ("neutral",   2.0),
    ("happy",     2.0),
    ("speaking",  3.0),    # gets sin amplitude
    ("focused",   2.0),
    ("thinking",  2.0),
    ("sad",       2.0),
    ("listening", 2.0),
]


def render_emotion(emotion: str, seconds: float) -> list[Image.Image]:
    adapter = MathAdapter()
    adapter.open(
        str(FACE_SCRIPT),
        width=WIDTH, height=HEIGHT,
        params={"emotion": emotion, "fps": FPS},
    )
    n_frames = int(seconds * FPS)
    frames: list[Image.Image] = []
    for i in range(n_frames):
        t = i / FPS
        # For "speaking", oscillate amplitude with a sin wave so the
        # mouth opens + closes — same shape the TTS amplitude pulse
        # produces during real conversation.
        if emotion == "speaking":
            amp = (math.sin(2 * math.pi * 5.0 * t) + 1.0) / 2.0
            amp = amp * 0.7 + 0.15
            adapter.set_runtime_param("amplitude", amp)
        frame = adapter.next_frame(t)
        if frame is None:
            break
        img = Image.frombytes(
            "RGBA", (WIDTH, HEIGHT), frame.data,
        ).convert("RGB")
        # Nearest-neighbor upscale so the pixel art reads big
        # + crisp on a normal display.  Native 64x64 frame
        # → 512x512 preview.
        img = img.resize(
            (WIDTH * SCALE, HEIGHT * SCALE),
            Image.NEAREST,
        )
        frames.append(img)
    return frames


def main() -> int:
    if not FACE_SCRIPT.exists():
        print(f"missing face script: {FACE_SCRIPT}", file=sys.stderr)
        return 1

    print("rendering Lilith demo —", end=" ", flush=True)
    all_frames: list[Image.Image] = []
    for emotion, seconds in EMOTIONS:
        print(emotion, end=" ", flush=True)
        all_frames.extend(render_emotion(emotion, seconds))
    print(f"({len(all_frames)} frames)")

    print(f"writing GIF → {OUT_GIF}")
    duration_ms = int(1000.0 / FPS)
    all_frames[0].save(
        OUT_GIF,
        save_all=True,
        append_images=all_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    print(f"opening {OUT_GIF}")
    try:
        subprocess.run(["open", str(OUT_GIF)], check=False)
    except Exception:
        print(f"(open manually: {OUT_GIF})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
