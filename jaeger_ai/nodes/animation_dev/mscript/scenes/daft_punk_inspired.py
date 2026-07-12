# assets/math/daft_punk_inspired.py
# A Python/NumPy animation inspired by Daft Punk LED helmets.

import numpy as np
from mscript.mochi_animations import Animation

class DaftPunkInspired(Animation):
    """
    A collection of animations inspired by Daft Punk helmets, ported from a C++
    project and optimized with NumPy. The animation cycles through different visual effects.
    """
    name = "daft_punk_inspired"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.color = (255, 255, 255)  # Use white for a monochrome look

        # Animation state management
        self.animations = [
            self._render_scanner,
            self._render_midline,
            self._render_spectrum,
            self._render_fade
        ]
        self.initializers = [
            self._init_scanner,
            self._init_midline,
            self._init_spectrum,
            self._init_fade
        ]
        self.current_animation_index = 0
        self.last_switch_time = 0.0
        self.demo_delay = 10.0  # seconds per animation

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs)
        self.current_animation_index = 0
        self.last_switch_time = 0.0
        self._init_all_animations()

    def on_exit(self):
        super().on_exit()

    def _init_all_animations(self):
        for init_func in self.initializers:
            init_func()

    # --- Animation Initializers ---
    def _init_scanner(self):
        self.scanner_pos = 0
        self.scanner_dir = 1
        self.scanner_width = 3

    def _init_midline(self):
        self.midline_pos = 0
        self.midline_dir = 1

    def _init_spectrum(self):
        # Using a pre-generated y-index array for performance
        self.y_indices = np.arange(self.h)[:, np.newaxis]

    def _init_fade(self):
        self.fade_intensity = 0.0
        self.fade_dir = 1.0

    # --- Animation Renderers ---
    def _render_scanner(self, frame):
        frame.fill(0)
        start = self.scanner_pos
        end = self.scanner_pos + self.scanner_width
        frame[:, start:end] = self.color

        self.scanner_pos += self.scanner_dir
        if self.scanner_pos <= 0 or (self.scanner_pos + self.scanner_width) >= self.w:
            self.scanner_dir *= -1

    def _render_midline(self, frame):
        frame.fill(0)
        frame[self.midline_pos, :] = self.color
        frame[self.h - 1 - self.midline_pos, :] = self.color

        self.midline_pos += self.midline_dir
        if self.midline_pos <= 0 or self.midline_pos >= self.h // 2:
            self.midline_dir *= -1

    def _render_spectrum(self, frame):
        frame.fill(0)
        heights = np.random.randint(0, self.h, size=self.w)
        mask = self.y_indices < heights
        frame[mask] = self.color

    def _render_fade(self, frame):
        intensity = int(self.fade_intensity * 255)
        frame[:, :] = (intensity, intensity, intensity)

        self.fade_intensity += self.fade_dir * 0.05
        if self.fade_intensity >= 1.0 or self.fade_intensity <= 0.0:
            self.fade_dir *= -1
            self.fade_intensity = np.clip(self.fade_intensity, 0, 1)

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        # Check if it's time to switch to the next animation
        if t - self.last_switch_time > self.demo_delay:
            self.last_switch_time = t
            self.current_animation_index = (self.current_animation_index + 1) % len(self.animations)
            # Initialize the new animation's state
            self.initializers[self.current_animation_index]()

        # Run the current animation
        current_animation_func = self.animations[self.current_animation_index]
        current_animation_func(frame)
