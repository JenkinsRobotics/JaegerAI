# animations/test_filled_rects.py
# A Python/NumPy recreation of the testFilledRects pattern from Adafruit GFX.

import numpy as np
import math
from mscript.mochi_animations import Animation

class TestFilledRects(Animation):
    name = "test_filled_rects"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color1 = (255, 255, 0)  # Default to Yellow
        self.color2 = (255, 0, 255)  # Default to Magenta

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        if "CLR" in kwargs and isinstance(kwargs["CLR"], list):
            self.color1 = tuple(kwargs["CLR"])
        if "CLR2" in kwargs and isinstance(kwargs["CLR2"], list):
            self.color2 = tuple(kwargs["CLR2"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        cx = self.w // 2
        cy = self.h // 2
        n = min(self.w, self.h)

        loop_duration = 5.0  # seconds for one full shrink/grow cycle
        phase = (t % loop_duration) / loop_duration
        
        current_size_factor = (math.cos(phase * 2 * math.pi) + 1) / 2 # Varies 1 -> 0 -> 1

        # Iterate from the outside in, drawing concentric rectangles
        for i in range(n, 0, -6):
            size = int(i * current_size_factor)
            if size <= 0:
                continue

            i2 = size // 2
            x = cx - i2
            y = cy - i2

            if x < 0 or y < 0 or x + size >= self.w or y + size >= self.h:
                continue

            # 1. fillRect -> NumPy slice assignment
            frame[y:y+size, x:x+size] = self.color1

            # 2. drawRect -> Four 1-pixel-wide slice assignments for the outline
            if size > 1: # Avoid drawing outline on a 1x1 rect
                frame[y:y+size, x:x+1] = self.color2         # Left
                frame[y:y+size, x+size-1:x+size] = self.color2 # Right
                frame[y:y+1, x:x+size] = self.color2         # Top
                frame[y+size-1:y+size, x:x+size] = self.color2 # Bottom
