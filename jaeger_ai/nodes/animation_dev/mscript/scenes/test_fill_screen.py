# animations/test_fill_screen.py
# A Python/NumPy recreation of the testFillScreen pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation
from mscript.gfx import parse_color

class TestFillScreen(Animation):
    name = "test_fill_screen"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        # Default color sequence from the C++ demo
        self.colors = [
            (0, 0, 0),      # Black
            (255, 0, 0),    # Red
            (0, 255, 0),    # Green
            (0, 0, 255),    # Blue
        ]
        self.duration_per_color = 0.75  # seconds

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # This handles the 'clear' flag
        
        # Allow overriding colors and duration for modular use
        if "colors" in kwargs and isinstance(kwargs["colors"], list):
            # Parse color names (e.g., "RED") or RGB tuples from the script
            self.colors = [parse_color(c) for c in kwargs["colors"]]
        
        if "duration" in kwargs:
            self.duration_per_color = float(kwargs["duration"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        # This animation always fills the screen, so clear_on_frame is implicitly true.
        # No need for an `if self.clear_on_frame:` check here.

        if not self.colors or self.duration_per_color <= 0:
            frame[:, :] = (0, 0, 0)
            return
            
        total_cycle_time = len(self.colors) * self.duration_per_color
        time_in_cycle = t % total_cycle_time
        color_index = int(time_in_cycle / self.duration_per_color)
        
        current_color = self.colors[color_index]

        # Fill the entire frame with the current color
        frame[:, :] = current_color
