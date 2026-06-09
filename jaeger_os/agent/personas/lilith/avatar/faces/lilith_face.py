"""Lilith — her face, as a procedural MathScript.

One file, all emotions.  The ``emotion`` kwarg passed via
``set_avatar_state(emotion=)`` shapes the eyes / mouth / brows;
the rest (breathing, blinking, idle micro-jitter) runs the same
regardless of emotion so she always feels alive.

Operator-locked aesthetic
─────────────────────────
- Dark background (OBS-friendly chroma-key alternative not needed
  on macOS Mission Control)
- Soft luminous face — readable at small size, looks intentional
  full-screen
- Big expressive eyes (they carry most of the emotion)
- Subtle, NOT cartoon — Lilith is a quiet, observant presence

Per-emotion parameters
──────────────────────
- ``neutral``    slight smile, regular eyes
- ``happy``      big arc smile, eyes squinted
- ``sad``        flat-frown mouth, droop eyelids
- ``focused``    flat mouth, narrowed eyes
- ``thinking``   slight purse, one brow raised
- ``speaking``   mouth open (amplitude wires in 0.5.x)
- ``listening``  closed-relaxed mouth, eyes wide

Set ``amplitude_param`` from a TTS-chunk subscriber (lands in the
next commit) to drive lip-sync on ``speaking``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from jaeger_os.nodes.animation.adapters import MathScript


# ── colour palette (RGB) ──────────────────────────────────────────

BG_DARK_NAVY   = (14, 26, 43)        # #0E1A2B — backdrop
FACE_GLOW      = (245, 240, 230)     # warm off-white
FACE_SHADOW    = (210, 200, 188)     # soft edge
EYE_DARK       = (20, 28, 42)        # iris + lash
EYE_HILITE     = (250, 248, 240)     # tiny highlight
MOUTH_DARK     = (60, 35, 45)        # lip line
CHEEK_FLUSH    = (235, 160, 165)     # happy-mode flush


class LilithFace(MathScript):
    """Parametric face renderer.  One MathScript, many emotions."""

    def on_enter(self, **kwargs: Any) -> None:
        self.emotion = str(kwargs.get("emotion", "neutral")).lower()
        # Amplitude param drives the mouth open shape during speaking.
        # 0.0..1.0; defaults to a small breathing pulse so the mouth
        # doesn't sit lifeless even before lip-sync wires up.
        self.amplitude_param = float(kwargs.get("amplitude", 0.0))
        # Idle micro-motion seeds (so multiple instances of Lilith
        # on screen wouldn't lock-step blink).
        self.blink_phase = float(kwargs.get("blink_phase", 0.0))
        self.breath_phase = float(kwargs.get("breath_phase", 0.0))

    def render_into(self, t: float, frame_rgb: np.ndarray) -> None:
        h, w, _ = frame_rgb.shape
        # ── background ─────────────────────────────────────────────
        frame_rgb[:, :] = BG_DARK_NAVY

        # ── breathing offset (subtle vertical sway) ────────────────
        breath = math.sin(2 * math.pi * (t * 0.5 + self.breath_phase))
        y_offset = int(round(breath * h * 0.005))  # half a percent

        # ── face oval ──────────────────────────────────────────────
        cx, cy = w // 2, h // 2 + y_offset
        face_rx = int(w * 0.30)
        face_ry = int(h * 0.36)
        _fill_ellipse(frame_rgb, cx, cy, face_rx, face_ry, FACE_GLOW)
        # soft shadow edge
        _draw_ellipse(frame_rgb, cx, cy, face_rx, face_ry, FACE_SHADOW)

        # ── blink (eye height multiplier 0..1) ─────────────────────
        # Random-ish blink cycle: long-open, short-closed.
        blink_cycle = (t + self.blink_phase) * 0.5
        # 0..1 sin-shape, then squashed so most of the time eyes are
        # open and there's a quick close roughly every 4 seconds.
        blink_x = (blink_cycle % 4.0) / 4.0
        if blink_x < 0.05:
            eye_h_mul = max(0.05, 1.0 - (blink_x / 0.05))
        elif blink_x < 0.10:
            eye_h_mul = (blink_x - 0.05) / 0.05
        else:
            eye_h_mul = 1.0

        # ── eyes (positions + emotion-driven shape) ────────────────
        eye_y = cy - int(h * 0.05)
        eye_dx = int(w * 0.10)
        eye_rx = int(w * 0.045)
        eye_ry = int(h * 0.06)
        # Per-emotion adjustments.
        if self.emotion == "happy":
            eye_ry = int(eye_ry * 0.55)  # squinted
        elif self.emotion == "sad":
            eye_y += int(h * 0.015)
        elif self.emotion == "focused":
            eye_ry = int(eye_ry * 0.75)  # narrowed
        elif self.emotion == "listening":
            eye_ry = int(eye_ry * 1.15)  # slightly wider
        # Apply blink multiplier last so it always pulls toward 0.
        eye_ry = max(2, int(eye_ry * eye_h_mul))

        for side in (-1, +1):
            ex = cx + side * eye_dx
            _fill_ellipse(frame_rgb, ex, eye_y, eye_rx, eye_ry,
                          EYE_DARK)
            if eye_h_mul > 0.4:  # show highlight only when eyes open
                _fill_ellipse(
                    frame_rgb,
                    ex - eye_rx // 3, eye_y - eye_ry // 3,
                    max(1, eye_rx // 4), max(1, eye_ry // 4),
                    EYE_HILITE,
                )

        # ── mouth (emotion + amplitude) ────────────────────────────
        mouth_y = cy + int(h * 0.16)
        mouth_w = int(w * 0.13)
        _draw_mouth(
            frame_rgb,
            cx=cx, cy=mouth_y,
            half_w=mouth_w,
            emotion=self.emotion,
            amplitude=self.amplitude_param,
        )

        # ── happy-mode cheek flush ─────────────────────────────────
        if self.emotion == "happy":
            cheek_y = cy + int(h * 0.05)
            cheek_dx = int(w * 0.17)
            cheek_r = int(w * 0.032)
            for side in (-1, +1):
                cxx = cx + side * cheek_dx
                _fill_ellipse_alpha(
                    frame_rgb,
                    cxx, cheek_y,
                    cheek_r, int(cheek_r * 0.7),
                    CHEEK_FLUSH, alpha=0.35,
                )

        # ── brow lift for 'thinking' ───────────────────────────────
        if self.emotion == "thinking":
            brow_y = eye_y - int(h * 0.04)
            brow_w = int(w * 0.04)
            # Right brow raised
            _draw_line(
                frame_rgb,
                cx + eye_dx - brow_w, brow_y + 4,
                cx + eye_dx + brow_w, brow_y - 4,
                EYE_DARK, thickness=2,
            )
            # Left brow neutral
            _draw_line(
                frame_rgb,
                cx - eye_dx - brow_w, brow_y,
                cx - eye_dx + brow_w, brow_y,
                EYE_DARK, thickness=2,
            )


# ── drawing primitives (numpy vectorised) ─────────────────────────

def _fill_ellipse(frame, cx, cy, rx, ry, color):
    if rx <= 0 or ry <= 0:
        return
    h, w, _ = frame.shape
    yy, xx = np.ogrid[:h, :w]
    mask = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    frame[mask] = color


def _draw_ellipse(frame, cx, cy, rx, ry, color, thickness=2):
    if rx <= 0 or ry <= 0:
        return
    h, w, _ = frame.shape
    yy, xx = np.ogrid[:h, :w]
    dist = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    mask = (dist <= 1.0) & (dist >= (1.0 - 0.06 * thickness))
    frame[mask] = color


def _fill_ellipse_alpha(frame, cx, cy, rx, ry, color, alpha):
    """Blend ``color`` at ``alpha`` over the ellipse area."""
    if rx <= 0 or ry <= 0:
        return
    h, w, _ = frame.shape
    yy, xx = np.ogrid[:h, :w]
    mask = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    src = frame[mask].astype(np.float32)
    dst = np.array(color, dtype=np.float32)
    blended = src * (1 - alpha) + dst * alpha
    frame[mask] = blended.astype(np.uint8)


def _draw_line(frame, x0, y0, x1, y1, color, thickness=1):
    """Cheap thick line via repeated 1-px Bresenham passes."""
    h, w, _ = frame.shape
    for t_off in range(-thickness // 2, thickness // 2 + 1):
        _bresenham(frame, x0, y0 + t_off, x1, y1 + t_off, color, h, w)


def _bresenham(frame, x0, y0, x1, y1, color, h, w):
    dx = abs(x1 - x0); sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0); sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        if 0 <= x0 < w and 0 <= y0 < h:
            frame[y0, x0] = color
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy; x0 += sx
        if e2 <= dx:
            err += dx; y0 += sy


def _draw_mouth(frame, cx, cy, half_w, emotion, amplitude):
    """Render a mouth shape for the given emotion + speech amplitude."""
    open_h = int(amplitude * half_w * 0.8) if emotion == "speaking" else 0

    if open_h > 2:
        # Open ellipse — speaking mouth.
        _fill_ellipse(frame, cx, cy, half_w, open_h, MOUTH_DARK)
        return

    # Closed mouth — draw a curve.
    if emotion == "happy":
        # Upturned arc.
        _draw_arc(frame, cx, cy, half_w, int(half_w * 0.4),
                  curve=+1, color=MOUTH_DARK, thickness=2)
    elif emotion == "sad":
        _draw_arc(frame, cx, cy, half_w, int(half_w * 0.3),
                  curve=-1, color=MOUTH_DARK, thickness=2)
    elif emotion == "focused":
        _draw_line(frame, cx - half_w, cy, cx + half_w, cy,
                   MOUTH_DARK, thickness=2)
    elif emotion == "thinking":
        # Slight purse: a small upward bow.
        _draw_arc(frame, cx, cy, int(half_w * 0.7), int(half_w * 0.2),
                  curve=+1, color=MOUTH_DARK, thickness=2)
    elif emotion == "listening":
        # Relaxed closed.
        _draw_arc(frame, cx, cy, half_w, int(half_w * 0.15),
                  curve=+1, color=MOUTH_DARK, thickness=2)
    else:
        # neutral / unknown — small subtle smile.
        _draw_arc(frame, cx, cy, half_w, int(half_w * 0.15),
                  curve=+1, color=MOUTH_DARK, thickness=2)


def _draw_arc(frame, cx, cy, half_w, depth, curve, color, thickness):
    """Draw a quadratic arc.  ``curve=+1`` is a SMILE (corners up,
    center dips down on screen).  ``curve=-1`` is a FROWN (center
    peaks up, corners down).  ``depth`` is the peak distance from
    the baseline.

    Note image y is positive-DOWN.  A smile has corners HIGHER on
    screen (smaller y) and the dip LOWER (larger y), so for
    curve=+1 we ADD depth*(1-u²) to cy.
    """
    h, w, _ = frame.shape
    prev = None
    steps = max(8, half_w * 2)
    for i in range(steps + 1):
        u = (i / steps) * 2 - 1   # -1..+1
        x = int(round(cx + u * half_w))
        y = int(round(cy + curve * depth * (1 - u * u)))
        if prev is not None:
            _draw_line(frame, prev[0], prev[1], x, y, color,
                       thickness=thickness)
        prev = (x, y)
