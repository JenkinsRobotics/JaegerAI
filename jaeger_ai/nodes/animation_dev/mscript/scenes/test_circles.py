# assets/math/test_circles.py
# A Python/NumPy recreation of the testCircles pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation

class TestCircles(Animation):
    name = "test_circles"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color = (255, 255, 255)  # Default to White
        self.radius = 10

        # Pre-calculate coordinate grids for vectorized drawing
        self._x_coords, self._y_coords = None, None
        self._rebuild_coords()

    def _rebuild_coords(self):
        self._y_coords, self._x_coords = np.mgrid[0:self.h, 0:self.w]

    def set_size(self, w: int, h: int):
        super().set_size(w, h)
        self._rebuild_coords()

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs) # Handles the 'clear' flag
        
        # Use standard uppercase argument keys
        if "CLR" in kwargs and isinstance(kwargs["CLR"], list):
            self.color = tuple(kwargs["CLR"])
        if "RAD" in kwargs:
            self.radius = int(kwargs["RAD"])

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)  # Clear to black

        if self.radius <= 0: return

        r2 = self.radius * 2
        outer_radius_sq = self.radius * self.radius
        inner_radius_sq = (self.radius - 1) * (self.radius - 1)

        # Loop over the positions for the circle centers
        for y in range(0, self.h + self.radius, r2):
            for x in range(0, self.w + self.radius, r2):
                dist_sq = (self._x_coords - x)**2 + (self._y_coords - y)**2
                outline_mask = (dist_sq >= inner_radius_sq) & (dist_sq < outer_radius_sq)
                frame[outline_mask] = self.color
