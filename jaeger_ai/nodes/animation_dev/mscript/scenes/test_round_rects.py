# animations/test_round_rects.py
# A Python/NumPy recreation of the testRoundRects pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation, clamp8
from mscript.gfx import draw_round_rect, parse_color

class TestRoundRects(Animation):
    name = "test_round_rects"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color = (255, 0, 0) # Default base color is Red
        self.is_dynamic_color = True # By default, color changes with size

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        if "color" in kwargs:
            # If a color is passed, use it as a fixed color
            self.color = parse_color(kwargs["color"], self.color)
            self.is_dynamic_color = False

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        cx = self.w // 2 - 1
        cy = self.h // 2 - 1
        n = min(self.w, self.h)

        loop_duration = 4.0
        phase = (t % loop_duration) / loop_duration
        i = int(n * phase)
        if i < 2:
            return

        i2 = i // 2
        x = cx - i2
        y = cy - i2

        # Determine the final color to use
        final_color = self.color
        if self.is_dynamic_color:
            # If no override, calculate color based on size, like the original demo
            final_color = (clamp8(self.color[0] * i // n),
                           clamp8(self.color[1] * i // n),
                           clamp8(self.color[2] * i // n))

        if x < 0 or y < 0 or x + i >= self.w or y + i >= self.h:
            return

        draw_round_rect(frame, x, y, i, i, i // 8, final_color)
