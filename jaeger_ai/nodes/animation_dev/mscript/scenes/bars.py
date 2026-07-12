# assets/math/bars.py
# Vertical sweeping bars using a sinusoidal profile.

import numpy as np
from mscript.mochi_animations import Animation


class Bars(Animation):
    name = "bars"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.speed = 2.0     # radians/sec for phase advance
        self.x_scale = 0.30  # spatial frequency along X
        # Foreground RGB.  The brightness column-mask multiplies into
        # this colour each frame.  Default to a warm magenta so a
        # "just-fire" mode-on gives the operator something visible
        # straight away.  Was never initialised before — render_into
        # threw "'Bars' object has no attribute 'fg'" hundreds of
        # times per second the moment the mode activated.
        self.fg = (255, 80, 200)
        self._x_coords = None
        self._rebuild_coords()

    def _rebuild_coords(self):
        self._x_coords = np.arange(self.w)

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.speed = float(kwargs.get("speed", self.speed))
        self.x_scale = float(kwargs.get("x_scale", self.x_scale))
        # Allow `fg` override via mscript / sidecar type_props.
        fg_raw = kwargs.get("fg")
        if fg_raw is not None:
            try:
                if isinstance(fg_raw, (list, tuple)) and len(fg_raw) == 3:
                    self.fg = tuple(int(c) for c in fg_raw)
                elif isinstance(fg_raw, int):
                    self.fg = (fg_raw, fg_raw, fg_raw)
            except (TypeError, ValueError):
                pass

    def set_color(self, color) -> None:
        """Hook for the animation node's `color` ctrl command —
        matches the convention SolidColorAnimation already uses."""
        if isinstance(color, (list, tuple)) and len(color) == 3:
            try:
                self.fg = tuple(int(c) for c in color)
            except (TypeError, ValueError):
                pass

    def set_size(self, w: int, h: int):
        super().set_size(w, h)
        self._rebuild_coords()

    def render_into(self, t: float, pixel_buf: bytearray):
        # Create a NumPy array that shares memory with the pixel buffer (no copy)
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        # Calculate the brightness value `v` for all columns at once.
        v = np.sin(t * self.speed + self._x_coords * self.x_scale) * 0.5 + 0.5  # Shape: (w,)

        # Use NumPy broadcasting to multiply the foreground color by the brightness values.
        # This creates a single row of colors. Shape: (w, 3)
        colors = v[:, np.newaxis] * np.array(self.fg)

        # Assign the calculated row to all rows of the frame. NumPy handles the tiling automatically.
        frame[:, :, :] = colors.astype(np.uint8)
