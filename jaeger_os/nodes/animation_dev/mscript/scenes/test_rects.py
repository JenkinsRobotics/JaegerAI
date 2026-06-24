# assets/math/test_rects.py
# A Python/NumPy recreation of the testRects pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation

class TestRects(Animation):
    name = "test_rects"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color = (0, 255, 0)  # Default to Green

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        # Use standard uppercase argument key
        if "CLR" in kwargs and isinstance(kwargs["CLR"], list):
            self.color = tuple(kwargs["CLR"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        cx = self.w // 2
        cy = self.h // 2
        n = min(self.w, self.h)

        loop_duration = 4.0  # seconds for one full expansion
        phase = (t % loop_duration) / loop_duration # 0.0 -> 1.0

        size = int(n * phase)
        if size < 2:
            return

        i2 = size // 2
        x = cx - i2
        y = cy - i2

        if x < 0 or y < 0 or x + size >= self.w or y + size >= self.h:
            return

        # drawRect is implemented as four 1-pixel-wide slice assignments
        frame[y:y+size, x:x+1] = self.color         # Left
        frame[y:y+size, x+size-1:x+size] = self.color # Right
        frame[y:y+1, x:x+size] = self.color         # Top
        frame[y+size-1:y+size, x:x+size] = self.color # Bottom
