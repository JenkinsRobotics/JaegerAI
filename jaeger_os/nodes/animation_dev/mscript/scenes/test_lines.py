# assets/math/test_lines.py
# A Python/NumPy recreation of the testLines pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation
from mscript.gfx import draw_line, parse_color

class TestLines(Animation):
    name = "test_lines"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color = (0, 255, 255)  # Default to Cyan
        self.current_test = 0
        self.last_switch_t = 0.0
        self.test_duration = 2.0  # seconds per test pattern

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        if "color" in kwargs:
            self.color = parse_color(kwargs["color"], self.color)
        
        if "duration" in kwargs:
            self.test_duration = float(kwargs["duration"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        # Cycle through the four different line patterns
        if t - self.last_switch_t > self.test_duration:
            self.current_test = (self.current_test + 1) % 4
            self.last_switch_t = t
            # If we are in additive mode, we should clear when the pattern changes
            if not self.clear_on_frame:
                 frame[:, :] = (0, 0, 0)

        w, h = self.w, self.h
        
        # The drawing logic remains the same, but now uses the modular color
        if self.current_test == 0:
            for x2 in range(0, w, 6):
                draw_line(frame, 0, 0, x2, h - 1, self.color)
            for y2 in range(0, h, 6):
                draw_line(frame, 0, 0, w - 1, y2, self.color)
        elif self.current_test == 1:
            for x2 in range(0, w, 6):
                draw_line(frame, w - 1, 0, x2, h - 1, self.color)
            for y2 in range(0, h, 6):
                draw_line(frame, w - 1, 0, 0, y2, self.color)
        elif self.current_test == 2:
            for x2 in range(0, w, 6):
                draw_line(frame, 0, h - 1, x2, 0, self.color)
            for y2 in range(0, h, 6):
                draw_line(frame, 0, h - 1, w - 1, y2, self.color)
        elif self.current_test == 3:
            for x2 in range(0, w, 6):
                draw_line(frame, w - 1, h - 1, x2, 0, self.color)
            for y2 in range(0, h, 6):
                draw_line(frame, w - 1, h - 1, 0, y2, self.color)
