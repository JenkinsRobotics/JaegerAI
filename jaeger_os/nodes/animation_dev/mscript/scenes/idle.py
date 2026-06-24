# animations/idle.py
# A simple, low-CPU idle animation with a gentle pulsing background.

import math
import numpy as np
from mscript.mochi_animations import Animation


class Idle(Animation):
    name = "idle"

    def render_into(self, t: float, pixel_buf: bytearray):
        # Create a NumPy array that shares memory with the pixel buffer (no copy)
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        # Calculate the pulsing brightness for the blue channel
        breath = (math.sin(t * 0.8) * 0.5 + 0.5) * 0.12
        tint = int(15 + breath * 80)
        blue_channel = min(255, 12 + tint)

        # Set the entire frame to the calculated color at once.
        # NumPy automatically broadcasts the single color across the whole array.
        frame[:, :] = (8, 8, blue_channel)
