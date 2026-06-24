# assets/math/rainbow.py
# Rainbow flow using three phase-shifted sinusoids (fast, branchless, pretty).

import math
import numpy as np
from mscript.mochi_animations import Animation


class Rainbow(Animation):
    name = "rainbow"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.speed = 20.0
        self._x_coords = None
        self._rebuild_coords()

    def _rebuild_coords(self):
        # Create a grid of x-coordinates, tiled vertically for each row.
        # This is done once when size changes, not per frame.
        x = np.arange(self.w)
        self._x_coords = np.tile(x, (self.h, 1))

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.speed = float(kwargs.get("speed", self.speed))

    def set_size(self, w: int, h: int):
        super().set_size(w, h)
        self._rebuild_coords()

    def render_into(self, t: float, pixel_buf: bytearray):
        # Create a NumPy array that shares memory with the pixel buffer (no copy)
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        # Perform calculations on the entire grid at once using NumPy.
        # This is the vectorized equivalent of the old nested loops.
        u = (self._x_coords + t * self.speed) / self.w
        
        # 2π/3 phase shifts
        phase_r = 2 * math.pi * u
        phase_g = phase_r + 2.094
        phase_b = phase_r + 4.188

        # Calculate all pixel values in three vectorized operations.
        r = ((np.sin(phase_r) + 1.0) * 127.5).astype(np.uint8)
        g = ((np.sin(phase_g) + 1.0) * 127.5).astype(np.uint8)
        b = ((np.sin(phase_b) + 1.0) * 127.5).astype(np.uint8)

        # Assign the channels back to the frame buffer. This is also vectorized.
        frame[:, :, 0] = r
        frame[:, :, 1] = g
        frame[:, :, 2] = b
