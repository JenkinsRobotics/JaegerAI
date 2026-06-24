# assets/math/daft_punk_inspired_geometric.py
# A Python/NumPy animation inspired by Daft Punk LED helmets, featuring geometric patterns.

import numpy as np
from mscript.mochi_animations import Animation

class DaftPunkGeometric(Animation):
    """
    A collection of geometric animations inspired by Daft Punk helmets.
    This animation cycles through different visual effects like scanners,
    wipers, and scrolling patterns, all rendered in color.
    """
    name = "daft_punk_geometric"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)

        # Animation state management
        self.animations = [
            self._render_scanner,
            self._render_midline,
            self._render_wiper,
            self._render_arrow_scroll,
            self._render_sinewave,
        ]
        self.initializers = [
            self._init_scanner,
            self._init_midline,
            self._init_wiper,
            self._init_arrow_scroll,
            self._init_sinewave,
        ]
        self.current_animation_index = 0
        self.last_switch_time = 0.0
        self.demo_delay = 10.0  # seconds per animation

    def _get_color(self, t: float):
        """Generates a smoothly cycling color."""
        r = (np.sin(t * 0.5) + 1) / 2
        g = (np.sin(t * 0.5 + 2 * np.pi / 3) + 1) / 2
        b = (np.sin(t * 0.5 + 4 * np.pi / 3) + 1) / 2
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
    def _init_scanner(self):
        self.scanner_pos = 0
        self.scanner_dir = 1
        self.scanner_width = 5
        self.last_scanner_update = 0.0
        self.scanner_delay = 0.05

    def _init_midline(self):
        self.midline_pos = 0
        self.midline_dir = 1
        self.last_midline_update = 0.0
        self.midline_delay = 0.1

    def _init_wiper(self):
        self.wiper_pos = 0
        self.wiper_dir = 1
        self.last_wiper_update = 0.0
        self.wiper_delay = 0.02

    def _init_arrow_scroll(self):
        self.arrow_scroll_idx = 0
        self.arrow_data = [0x3c, 0x66, 0xc3, 0x99]
        self.last_arrow_update = 0.0
        self.arrow_delay = 0.1

    def _init_sinewave(self):
        self.sinewave_idx = 0
        self.sinewave_data = [8, 6, 1, 6, 24, 96, 128, 96, 16]
        self.last_sinewave_update = 0.0
        self.sinewave_delay = 0.05

    # --- Animation Renderers ---
    def _render_scanner(self, frame, color, t):
        if t - self.last_scanner_update < self.scanner_delay:
            return
        self.last_scanner_update = t
        
        frame.fill(0)
        start = self.scanner_pos
        end = self.scanner_pos + self.scanner_width
        frame[:, start:end] = color

        self.scanner_pos += self.scanner_dir
        if self.scanner_pos <= 0 or (self.scanner_pos + self.scanner_width) >= self.w:
            self.scanner_dir *= -1

    def _render_midline(self, frame, color, t):
        if t - self.last_midline_update < self.midline_delay:
            return
        self.last_midline_update = t

        frame.fill(0)
        frame[self.midline_pos, :] = color
        frame[self.h - 1 - self.midline_pos, :] = color

        self.midline_pos += self.midline_dir
        if self.midline_pos <= 0 or self.midline_pos >= self.h // 2:
            self.midline_dir *= -1
            if self.midline_pos < 0: self.midline_pos = 0

    def _render_wiper(self, frame, color, t):
        if t - self.last_wiper_update < self.wiper_delay:
            return
        self.last_wiper_update = t

        if 0 <= self.wiper_pos < self.w:
            col_color = color if self.wiper_dir == 1 else (0, 0, 0)
            frame[:, self.wiper_pos] = col_color

        self.wiper_pos += self.wiper_dir
        if self.wiper_pos >= self.w or self.wiper_pos < 0:
            self.wiper_dir *= -1
            self.wiper_pos += self.wiper_dir

    def _render_arrow_scroll(self, frame, color, t):
        if t - self.last_arrow_update < self.arrow_delay:
            return
        self.last_arrow_update = t

        frame[:, :-1] = frame[:, 1:]
        
        col_data = self.arrow_data[self.arrow_scroll_idx]
        new_col = np.zeros((self.h, 3), dtype=np.uint8)
        for i in range(min(self.h, 8)):
            if (col_data >> i) & 1:
                new_col[i] = color
        frame[:, -1] = new_col

        self.arrow_scroll_idx = (self.arrow_scroll_idx + 1) % len(self.arrow_data)

    def _render_sinewave(self, frame, color, t):
        if t - self.last_sinewave_update < self.sinewave_delay:
            return
        self.last_sinewave_update = t

        frame[:, :-1] = frame[:, 1:]

        col_data = self.sinewave_data[self.sinewave_idx]
        new_col = np.zeros((self.h, 3), dtype=np.uint8)
        for i in range(min(self.h, 8)):
            if (col_data >> i) & 1:
                new_col[i] = color
        frame[:, -1] = new_col

        self.sinewave_idx = (self.sinewave_idx + 1) % len(self.sinewave_data)

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
