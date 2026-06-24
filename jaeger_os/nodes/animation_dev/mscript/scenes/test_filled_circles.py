# animations/test_filled_circles.py
# A Python/NumPy recreation of the testFilledCircles pattern from Adafruit GFX.

import numpy as np
from mscript.mochi_animations import Animation

class TestFilledCircles(Animation):
    name = "test_filled_circles"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color = (255, 0, 255)  # Default to Magenta
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
        r_squared = self.radius * self.radius

        # Loop over the positions for the circle centers
        for y in range(self.radius, self.h, r2):
            for x in range(self.radius, self.w, r2):
                # Create a boolean mask for all pixels inside the current circle.
                circle_mask = (self._x_coords - x)**2 + (self._y_coords - y)**2 <= r_squared
                
                # Apply the mask to the frame to color the circle.
                frame[circle_mask] = self.color
