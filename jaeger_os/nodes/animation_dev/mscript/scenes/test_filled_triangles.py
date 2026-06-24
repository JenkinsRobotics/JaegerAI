# animations/test_filled_triangles.py
# A Python/NumPy recreation of the testFilledTriangles pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation, clamp8
from mscript.gfx import draw_triangle, fill_triangle, parse_color

class TestFilledTriangles(Animation):
    name = "test_filled_triangles"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color1_override = None # For fill
        self.color2_override = None # For outline

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        if "color1" in kwargs:
            self.color1_override = parse_color(kwargs["color1"])
        if "color2" in kwargs:
            self.color2_override = parse_color(kwargs["color2"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        cx = self.w // 2 - 1
        cy = self.h // 2 - 1
        n = min(cx, cy)

        loop_duration = 5.0  # seconds for one full shrink cycle
        phase = (t % loop_duration) / loop_duration  # 0.0 -> 1.0

        i = int(n * (1.0 - phase))

        if i > 10:
            # Use override colors if provided, otherwise use dynamic colors
            fill_color = self.color1_override if self.color1_override else (0, clamp8(i), clamp8(i))
            outline_color = self.color2_override if self.color2_override else (clamp8(i), clamp8(i), 0)

            fill_triangle(
                frame,
                cx, cy - i, cx - i, cy + i, cx + i, cy + i,
                fill_color
            )
            draw_triangle(
                frame,
                cx, cy - i, cx - i, cy + i, cx + i, cy + i,
                outline_color
            )
