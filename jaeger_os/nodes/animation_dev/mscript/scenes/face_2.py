# animations/face_2.py
# Variant of the original inline face animation (breathing bg, eyes, blink, pupils, mouth).

import math, random, time
import numpy as np
from mscript.mochi_animations import Animation, clamp8


class Face2(Animation):
    name = "face_2"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        # palette
        self.eye_white = (235, 235, 255)
        self.pupil_col = (25, 25, 40)
        self.lid_col   = (230, 230, 240)
        self.bg_base   = (8, 8, 12)
        self.mouth_col = (255, 120, 120)

        # dynamics
        self._next_blink_t = time.time() + random.uniform(3.0, 7.0)
        self._blink_dur = 0.12
        self._blink_end_t = None

        # NumPy coordinate grids
        self._x_coords, self._y_coords = None, None
        self._rebuild_coords()

    def _rebuild_coords(self):
        self._y_coords, self._x_coords = np.mgrid[0:self.h, 0:self.w]

    def set_size(self, w: int, h: int):
        super().set_size(w, h)
        self._rebuild_coords()

    def on_event(self, event: str, **kwargs):
        e = (event or "").lower()
        if e == "blink":
            now = time.time()
            self._blink_end_t = now + self._blink_dur
            self._next_blink_t = now + random.uniform(3.0, 7.0)

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        # --- breathing background ---
        breath = (math.sin(t * 0.8) * 0.5 + 0.5) * 0.12
        tint_b = clamp8(int(12 + (15 + breath * 80)))
        frame[:, :] = (self.bg_base[0], self.bg_base[1], tint_b)

        # --- geometry ---
        eye_y = self.h // 2 - 2
        eye_dx = max(1, self.w // 6)
        lx, rx = self.w // 2 - eye_dx, self.w // 2 + eye_dx
        r_eye = max(2, self.w // 10)

        # --- eyes (two discs) ---
        r2 = r_eye * r_eye
        left_eye_mask = (self._x_coords - lx)**2 + (self._y_coords - eye_y)**2 <= r2
        right_eye_mask = (self._x_coords - rx)**2 + (self._y_coords - eye_y)**2 <= r2
        frame[left_eye_mask | right_eye_mask] = self.eye_white

        # --- pupils (filled small discs) ---
        pr = max(1, r_eye - 2)
        pr2 = pr * pr
        left_pupil_mask = (self._x_coords - lx)**2 + (self._y_coords - eye_y)**2 <= pr2
        right_pupil_mask = (self._x_coords - rx)**2 + (self._y_coords - eye_y)**2 <= pr2
        frame[left_pupil_mask | right_pupil_mask] = self.pupil_col

        # --- Blink timing ---
        now_real = time.time()
        if self._blink_end_t is None and now_real >= self._next_blink_t:
            self._blink_end_t = now_real + self._blink_dur

        if self._blink_end_t is not None:
            phase = 1.0 - max(0.0, (self._blink_end_t - now_real) / self._blink_dur)
            blink_amt = max(0.0, min(1.0, phase))
            if now_real >= self._blink_end_t:
                self._blink_end_t = None
                self._next_blink_t = now_real + random.uniform(3.0, 7.0)

            # Eyelid line (blink)
            if blink_amt > 0:
                lid_y = eye_y - r_eye + int(blink_amt * (r_eye * 2))
                if 0 <= lid_y < self.h:
                    frame[lid_y, (lx - r_eye):(lx + r_eye + 1)] = self.lid_col
                    frame[lid_y, (rx - r_eye):(rx + r_eye + 1)] = self.lid_col

        # --- mouth ---
        mouth_y = self.h // 2 + r_eye + 2
        width = self.w // 4
        vu = (math.sin(t * 3.1) * 0.5 + 0.5) * 0.5
        open_amt = int(min(self.h // 6, 1 + int(vu * 4)))
        
        y_start = mouth_y
        y_end = min(self.h, mouth_y + open_amt)
        x_start = self.w // 2 - width // 2
        x_end = self.w // 2 + width // 2

        if y_start < y_end and x_start < x_end:
            frame[y_start:y_end, x_start:x_end] = self.mouth_col
