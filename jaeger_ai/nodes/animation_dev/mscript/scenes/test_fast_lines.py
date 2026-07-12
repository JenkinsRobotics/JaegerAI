# animations/test_fast_lines.py
# A Python/NumPy recreation of the testFastLines pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation

class TestFastLines(Animation):
    name = "test_fast_lines"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color1 = (255, 0, 0)  # Default to Red
        self.color2 = (0, 0, 255)  # Default to Blue

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        # Use standard uppercase argument keys
        if "CLR" in kwargs and isinstance(kwargs["CLR"], list):
            self.color1 = tuple(kwargs["CLR"])
        if "CLR2" in kwargs and isinstance(kwargs["CLR2"], list):
            self.color2 = tuple(kwargs["CLR2"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        # Draw horizontal lines
        for y in range(0, self.h, 5):
            frame[y, :] = self.color1

        # Draw vertical lines
        for x in range(0, self.w, 5):
            frame[:, x] = self.color2
