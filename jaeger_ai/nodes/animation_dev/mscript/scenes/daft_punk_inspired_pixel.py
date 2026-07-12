# assets/math/daft_punk_inspired_pixel.py
# A Python/NumPy animation inspired by Daft Punk LED helmets, featuring pixel-based effects.

import numpy as np
from mscript.mochi_animations import Animation

class DaftPunkPixel(Animation):
    """
    A collection of pixel-based animations inspired by Daft Punk helmets.
    This animation cycles through effects like random pixel noise, spectrum
    analyzers, and full-screen fades, all rendered in vibrant, cycling colors.
    """
    name = "daft_punk_pixel"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)

        # Animation state management
        self.animations = [
            self._render_random,
            self._render_spectrum,
            self._render_fade,
        ]
        self.initializers = [
            self._init_random,
            self._init_spectrum,
            self._init_fade,
        ]
        self.current_animation_index = 0
        self.last_switch_time = 0.0
        self.demo_delay = 10.0  # seconds per animation

    def _get_color(self, t: float, offset: float = 0.0):
        """Generates a smoothly cycling color with an optional offset."""
        r = (np.sin(t * 0.5 + offset) + 1) / 2
        g = (np.sin(t * 0.5 + offset + 2 * np.pi / 3) + 1) / 2
        b = (np.sin(t * 0.5 + offset + 4 * np.pi / 3) + 1) / 2
        return (int(r * 255), int(g * 255), int(b * 255))

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
    def _init_random(self):
        self.last_random_update = 0.0
        self.random_delay = 0.1

    def _init_spectrum(self):
        self.y_indices = np.arange(self.h)[:, np.newaxis]
        self.last_spectrum_update = 0.0
        self.spectrum_delay = 0.1

    def _init_fade(self):
        self.fade_intensity = 0.0
        self.fade_dir = 1.0
        self.last_fade_update = 0.0
        self.fade_delay = 0.05

    # --- Animation Renderers ---
    def _render_random(self, frame, color, t):
        if t - self.last_random_update < self.random_delay:
            return
        self.last_random_update = t

        random_pixels = np.random.randint(0, 2, size=(self.h, self.w), dtype=bool)
        frame[random_pixels] = color
        frame[~random_pixels] = (0, 0, 0)

    def _render_spectrum(self, frame, color, t):
        if t - self.last_spectrum_update < self.spectrum_delay:
            return
        self.last_spectrum_update = t

        frame.fill(0)
        heights = np.random.randint(0, self.h + 1, size=self.w)
        mask = self.y_indices < heights
        frame[mask] = color

    def _render_fade(self, frame, color, t):
        if t - self.last_fade_update < self.fade_delay:
            return
        self.last_fade_update = t

        intensity_val = self.fade_intensity * np.array(color)
        frame[:, :] = intensity_val.astype(np.uint8)

        self.fade_intensity += self.fade_dir * 0.05
        if self.fade_intensity >= 1.0 or self.fade_intensity <= 0.0:
            self.fade_dir *= -1
            self.fade_intensity = np.clip(self.fade_intensity, 0, 1)

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        color = self._get_color(t)

        if t - self.last_switch_time > self.demo_delay:
            self.last_switch_time = t
            self.current_animation_index = (self.current_animation_index + 1) % len(self.animations)
            self.initializers[self.current_animation_index]()
            frame.fill(0)

        current_animation_func = self.animations[self.current_animation_index]
        current_animation_func(frame, color, t)
