"""Lilith — Mochi-style chibi face, native 64x64 LED matrix.

Operator-locked aesthetic (2026-06-09): matches Mochi's reference
sheet at ``Mochi/assets/video/mochi enhance/mochi_2025-10-01_23-06-48-967.jpeg``:

  - Pure black background
  - Two big white "pill" eyes (stadium shape — flat sides,
    semicircle top + bottom) — filled solid white, no pupils
    in resting states
  - Thin 1-pixel mouth curves (smile / frown / o)
  - Special states swap eye shape / colour entirely
    (angry ``><`` shapes, sleepy ``- -`` lines, heart eyes, etc.)

Native size 64x64.  Hard pixel edges throughout — never anti-
aliased.  Integer-multiple upscaling (4x / 8x / 16x) preserves
the LED-matrix look on a regular screen.

Per-emotion shaping
───────────────────
- ``neutral``    pill eyes + small upward-curve smile
- ``happy``      pill eyes + wider smile curve
- ``sad``        pill eyes (lower) + frown curve
- ``focused``    pill eyes + flat dash mouth
- ``thinking``   one pill + one dot + small purse
- ``speaking``   pill eyes + open mouth rectangle whose height is
                 set by ``amplitude_param`` (lip sync)
- ``listening``  pill eyes (looking up — pupils added) + soft smile

Auto motion runs regardless of emotion:
- Subtle background tint pulse (breathing)
- Random blink every ~3-5 s — closes the pill eyes to a single
  horizontal line for ~100 ms
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from jaeger_ai.nodes.animation.adapters import MathScript


# ── Mochi palette ────────────────────────────────────────────────

BG_BLACK   = (0, 0, 0)
EYE_WHITE  = (255, 255, 255)
MOUTH_COL  = (255, 255, 255)        # white mouth (Mochi default)
SLEEPY_COL = (180, 180, 180)        # dimmed lines for sleepy state
PUPIL_DARK = (20, 20, 30)


class LilithFace(MathScript):
    """Native 64x64 chibi face renderer."""

    amplitude_param: float = 0.0

    def on_enter(self, **kwargs: Any) -> None:
        self.emotion = str(kwargs.get("emotion", "neutral")).lower()
        self.blink_phase = float(kwargs.get("blink_phase", 0.0))
        self.breath_phase = float(kwargs.get("breath_phase", 0.0))
        amp_kw = kwargs.get("amplitude")
        if amp_kw is not None:
            self.amplitude_param = float(amp_kw)

    # ── render ──────────────────────────────────────────────────

    def render_into(self, t: float, frame_rgb: np.ndarray) -> None:
        h, w, _ = frame_rgb.shape

        # ── background (subtle blue breath tint) ────────────────
        breath = (math.sin(t * 0.8 + self.breath_phase) * 0.5 + 0.5)
        tint_b = int(breath * 8)  # 0..8 — almost imperceptible
        frame_rgb[:, :] = (0, 0, tint_b)

        # ── geometry (scales with canvas) ───────────────────────
        # Anchor eyes at upper-third so mouth has room.
        eye_w = max(4, w // 5)          # 64x64 → 12 wide
        eye_h = max(6, w // 4)          # 64x64 → 16 tall
        eye_y = h // 2 - max(1, h // 16)  # 64x64 → 28 (centre y)
        eye_dx = max(2, w // 6)         # 64x64 → 10 spacing
        lx = w // 2 - eye_dx
        rx = w // 2 + eye_dx
        mouth_y = eye_y + eye_h // 2 + max(2, h // 10)  # 64x64 → 42

        # ── blink (auto) ────────────────────────────────────────
        blink = self._blink_amount(t)

        # ── per-emotion render ──────────────────────────────────
        e = self.emotion
        if blink >= 0.7:
            # Mid-blink: eyes collapse to a single horizontal line.
            self._draw_closed_eyes(frame_rgb, lx, rx, eye_y, eye_w,
                                    EYE_WHITE)
        elif e == "thinking":
            # One pill + one dot (the squinting eye).
            self._draw_pill(frame_rgb, lx, eye_y, eye_w, eye_h,
                             EYE_WHITE)
            self._draw_closed_eye(frame_rgb, rx, eye_y, eye_w,
                                   EYE_WHITE)
        elif e == "focused":
            # Slightly narrowed pills (75% height).
            self._draw_pill(frame_rgb, lx, eye_y, eye_w,
                             int(eye_h * 0.75), EYE_WHITE)
            self._draw_pill(frame_rgb, rx, eye_y, eye_w,
                             int(eye_h * 0.75), EYE_WHITE)
        elif e == "sad":
            # Pills drop 2 px lower for a "looking down" feel.
            self._draw_pill(frame_rgb, lx, eye_y + 2, eye_w, eye_h,
                             EYE_WHITE)
            self._draw_pill(frame_rgb, rx, eye_y + 2, eye_w, eye_h,
                             EYE_WHITE)
        else:
            # neutral / happy / speaking / listening — standard pills.
            self._draw_pill(frame_rgb, lx, eye_y, eye_w, eye_h,
                             EYE_WHITE)
            self._draw_pill(frame_rgb, rx, eye_y, eye_w, eye_h,
                             EYE_WHITE)
            # "listening" gets little upward-looking pupils.
            if e == "listening":
                self._draw_pupil(frame_rgb, lx, eye_y - eye_h // 4,
                                  max(2, eye_w // 4))
                self._draw_pupil(frame_rgb, rx, eye_y - eye_h // 4,
                                  max(2, eye_w // 4))

        # ── mouth ───────────────────────────────────────────────
        self._draw_mouth(frame_rgb, w, h, mouth_y)

    # ── primitives ───────────────────────────────────────────────

    def _draw_pill(
        self,
        frame: np.ndarray,
        cx: int, cy: int,
        w: int, h: int,
        color: tuple,
    ) -> None:
        """Mochi-style rounded rectangle — mostly rectangular with
        small corner rounding (~2 px radius).  Reads as a vertical
        lozenge at 64x64 LED matrix size.  Filled solid."""
        H, W, _ = frame.shape
        # Corner radius scales with eye size but stays small —
        # we want crisp rectangular sides, not a stadium.
        corner_r = max(1, min(w, h) // 6)
        half_w = w // 2
        half_h = h // 2
        # Fill the full rectangle first.
        x0 = max(0, cx - half_w)
        x1 = min(W, cx + half_w + 1)
        y0 = max(0, cy - half_h)
        y1 = min(H, cy + half_h + 1)
        if x0 < x1 and y0 < y1:
            frame[y0:y1, x0:x1] = color
        # Knock out the 4 corner squares of size (corner_r × corner_r)
        # that aren't inside the rounded arc.  We do this by setting
        # them to black (background) where they're OUTSIDE the
        # quarter-circle inset.
        if corner_r > 0:
            yy, xx = np.ogrid[:H, :W]
            # Corner centres are inset corner_r from the rectangle
            # corner.
            corners = (
                (cx - half_w + corner_r, cy - half_h + corner_r),
                (cx + half_w - corner_r, cy - half_h + corner_r),
                (cx - half_w + corner_r, cy + half_h - corner_r),
                (cx + half_w - corner_r, cy + half_h - corner_r),
            )
            for (ccx, ccy) in corners:
                # The corner square is the small square OUTSIDE the
                # corner centre (toward the rectangle corner).
                # Pixels in this square that are FURTHER than
                # corner_r from the corner centre get knocked out.
                cx_lo = ccx - corner_r if ccx < cx else ccx
                cx_hi = ccx + 1 if ccx < cx else ccx + corner_r + 1
                cy_lo = ccy - corner_r if ccy < cy else ccy
                cy_hi = ccy + 1 if ccy < cy else ccy + corner_r + 1
                cx_lo, cx_hi = max(0, cx_lo), min(W, cx_hi)
                cy_lo, cy_hi = max(0, cy_lo), min(H, cy_hi)
                if cx_lo >= cx_hi or cy_lo >= cy_hi:
                    continue
                square_yy = yy[cy_lo:cy_hi, :]
                square_xx = xx[:, cx_lo:cx_hi]
                yy_local = np.arange(cy_lo, cy_hi).reshape(-1, 1)
                xx_local = np.arange(cx_lo, cx_hi).reshape(1, -1)
                dist_sq = (xx_local - ccx) ** 2 + (yy_local - ccy) ** 2
                outside = dist_sq > corner_r * corner_r
                frame[cy_lo:cy_hi, cx_lo:cx_hi][outside] = BG_BLACK

    def _draw_closed_eye(
        self,
        frame: np.ndarray,
        cx: int, cy: int,
        w: int,
        color: tuple,
    ) -> None:
        """A single horizontal line — the squinted/winked eye."""
        H, W, _ = frame.shape
        x0 = max(0, cx - w // 2)
        x1 = min(W, cx + w // 2)
        if 0 <= cy < H and x0 < x1:
            frame[cy, x0:x1] = color

    def _draw_closed_eyes(
        self,
        frame: np.ndarray,
        lx: int, rx: int,
        cy: int, w: int,
        color: tuple,
    ) -> None:
        self._draw_closed_eye(frame, lx, cy, w, color)
        self._draw_closed_eye(frame, rx, cy, w, color)

    def _draw_pupil(
        self,
        frame: np.ndarray,
        cx: int, cy: int,
        r: int,
    ) -> None:
        H, W, _ = frame.shape
        yy, xx = np.ogrid[:H, :W]
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
        frame[mask] = PUPIL_DARK

    def _blink_amount(self, t: float) -> float:
        """0.0 = open, 1.0 = fully closed.  Period ≈ 4 s."""
        cycle = (t + self.blink_phase) * 0.5
        x = (cycle % 4.0) / 4.0
        if x < 0.04:
            return x / 0.04
        if x < 0.08:
            return 1.0 - (x - 0.04) / 0.04
        return 0.0

    def _draw_mouth(
        self,
        frame: np.ndarray,
        w: int, h: int,
        baseline_y: int,
    ) -> None:
        e = self.emotion
        cx = w // 2
        mouth_w = max(8, w // 4)

        if e == "speaking":
            # Open mouth rectangle whose height grows with amplitude.
            half_w = max(3, mouth_w // 2 - 1)
            open_h = max(2, int(self.amplitude_param * 6) + 2)
            y0, y1 = baseline_y, min(h, baseline_y + open_h)
            x0 = max(0, cx - half_w)
            x1 = min(w, cx + half_w)
            if y0 < y1 and x0 < x1:
                frame[y0:y1, x0:x1] = MOUTH_COL
            return

        if e == "happy":
            # Wider smile curve — bigger arc depth.
            self._draw_smile_curve(frame, w, h, baseline_y,
                                    half_w=mouth_w // 2,
                                    depth=2, color=MOUTH_COL)
            return

        if e == "sad":
            self._draw_frown_curve(frame, w, h, baseline_y,
                                    half_w=mouth_w // 2,
                                    depth=2, color=MOUTH_COL)
            return

        if e == "focused":
            # Flat dash, slightly shorter than default.
            half_w = max(3, mouth_w // 3)
            x0 = max(0, cx - half_w)
            x1 = min(w, cx + half_w)
            if 0 <= baseline_y < h and x0 < x1:
                frame[baseline_y, x0:x1] = MOUTH_COL
            return

        if e == "thinking":
            # Tiny purse, off-centre right.
            x0 = max(0, cx + 1)
            x1 = min(w, cx + max(3, mouth_w // 4))
            if 0 <= baseline_y < h and x0 < x1:
                frame[baseline_y, x0:x1] = MOUTH_COL
            return

        # neutral / listening / unknown — soft smile (depth 1).
        self._draw_smile_curve(frame, w, h, baseline_y,
                                half_w=mouth_w // 2,
                                depth=1, color=MOUTH_COL)

    def _draw_smile_curve(
        self,
        frame: np.ndarray,
        w: int, h: int,
        baseline_y: int,
        half_w: int, depth: int,
        color: tuple,
    ) -> None:
        """1-pixel-thick upward arc (corners up).  ``depth`` = how
        many px the centre dips below the baseline."""
        cx = w // 2
        H, W, _ = frame.shape
        steps = max(8, half_w * 2)
        for i in range(steps + 1):
            u = (i / steps) * 2 - 1   # -1..+1
            x = int(round(cx + u * half_w))
            y = int(round(baseline_y + depth * (1 - u * u)))
            if 0 <= x < W and 0 <= y < H:
                frame[y, x] = color

    def _draw_frown_curve(
        self,
        frame: np.ndarray,
        w: int, h: int,
        baseline_y: int,
        half_w: int, depth: int,
        color: tuple,
    ) -> None:
        """1-pixel-thick downward arc (corners down)."""
        cx = w // 2
        H, W, _ = frame.shape
        steps = max(8, half_w * 2)
        for i in range(steps + 1):
            u = (i / steps) * 2 - 1
            x = int(round(cx + u * half_w))
            y = int(round(baseline_y - depth * (1 - u * u)))
            if 0 <= x < W and 0 <= y < H:
                frame[y, x] = color
