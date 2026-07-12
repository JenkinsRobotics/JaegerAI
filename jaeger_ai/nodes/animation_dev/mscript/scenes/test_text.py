# assets/math/test_text.py
# A Python/NumPy recreation of the testText pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation
from mscript.gfx import draw_text

class TestText(Animation):
    name = "test_text"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        # Default parameters
        self.text = "Hello World!"
        self.color = (255, 255, 255) # White
        self.size = 1
        self.x = 0
        self.y = 0

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag

        # Use standard uppercase argument keys
        if "TXT" in kwargs:
            self.text = str(kwargs["TXT"])
        if "CLR" in kwargs and isinstance(kwargs["CLR"], list):
            self.color = tuple(kwargs["CLR"])
        if "SZ" in kwargs:
            self.size = int(kwargs["SZ"])
        if "X" in kwargs:
            self.x = int(kwargs["X"])
        if "Y" in kwargs:
            self.y = int(kwargs["Y"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        # Draw the text using the modular parameters
        draw_text(frame, self.x, self.y, self.text, self.color, self.size)
