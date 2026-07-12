# assets/math/test_triangles.py
# A Python/NumPy recreation of the testTriangles pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation, clamp8
from mscript.gfx import draw_triangle

class TestTriangles(Animation):
    name = "test_triangles"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color_override = None # If set, overrides the dynamic color

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        # Use standard uppercase argument key
        if "CLR" in kwargs and isinstance(kwargs["CLR"], list):
            self.color_override = tuple(kwargs["CLR"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        cx = self.w // 2 - 1
        cy = self.h // 2 - 1
        n = min(cx, cy)

        loop_duration = 5.0  # seconds for one full expansion
        phase = (t % loop_duration) / loop_duration  # 0.0 -> 1.0

        i = int(n * phase)

        # Use the override color if provided, otherwise use the dynamic color from the demo
        color = self.color_override if self.color_override else (0, 0, clamp8(i))

        draw_triangle(
            frame,
            cx, cy - i,       # peak
            cx - i, cy + i,   # bottom left
            cx + i, cy + i,   # bottom right
            color
        )
