# assets/math/wave_scene.py
# A Python/NumPy port of the C++ WaveScene animation.

import numpy as np
from mscript.mochi_animations import Animation

class WaveScene(Animation):
    """
    A fluid dynamics simulation where pixel values represent wave height.
    The wave propagates to its neighbors and creates complex visual patterns.
    Ported from a C++ implementation and optimized with NumPy.
    """
    name = "wave_scene"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        # Use float32 for the wave map to match C++ float type
        self.wave_map = np.zeros((self.h, self.w), dtype=np.float32)

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs)
        # On entering the scene, initialize the map with random values
        self.wave_map = np.random.rand(self.h, self.w).astype(np.float32)

    def update_wave(self):
        """
        Updates the wave map using a fully vectorized NumPy implementation for
        high performance.
        """
        last_map = self.wave_map

        # --- Step 1: Initial decay ---
        decay_randomness = np.random.rand(self.h, self.w).astype(np.float32)
        new_map = last_map * (0.96 + 0.02 * decay_randomness)

        # --- Step 2: Identify cells that can be influenced by neighbors ---
        low_value_threshold_randomness = np.random.rand(self.h, self.w).astype(np.float32)
        low_value_mask = last_map <= (0.18 + 0.04 * low_value_threshold_randomness)

        # --- Step 3: Calculate neighbor contributions ---
        total_contribution = np.zeros_like(last_map, dtype=np.float32)
        neighbor_count = np.zeros_like(last_map, dtype=np.int8)

        for v in range(-1, 2):
            for u in range(-1, 2):
                if u == 0 and v == 0:
                    continue

                neighbor_map = np.roll(np.roll(last_map, v, axis=0), u, axis=1)

                neighbor_threshold_randomness = np.random.rand(self.h, self.w).astype(np.float32)
                high_neighbor_mask = neighbor_map >= (0.5 + 0.04 * neighbor_threshold_randomness)

                contribution_randomness = np.random.rand(self.h, self.w).astype(np.float32)
                contribution = neighbor_map * (0.8 + 0.4 * contribution_randomness)

                total_contribution += contribution * high_neighbor_mask
                neighbor_count += high_neighbor_mask

        # --- Step 4: Update the cells based on neighbor contributions ---
        update_mask = low_value_mask & (neighbor_count > 0)
        
        values_to_update = new_map[update_mask]
        contributions_for_update = total_contribution[update_mask]
        counts_for_update = neighbor_count[update_mask]

        updated_values = (values_to_update + contributions_for_update) / counts_for_update

        new_map[update_mask] = updated_values

        # --- Step 5: Clamp final values and update the wave map ---
        self.wave_map = np.clip(new_map, 0, 1.0)

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        self.update_wave()

        m = self.wave_map

        # Vectorized color calculation
        r = np.power(m, 4 + (m * 0.5)) * np.cos(m)
        g = np.power(m, 3 + (m * 0.5)) * np.sin(m)
        b = np.power(m, 2 + (m * 0.5))

        rgb_image = np.stack([
            np.clip(r, 0, 1),
            np.clip(g, 0, 1),
            np.clip(b, 0, 1)
        ], axis=-1)
        
        rgb_image_uint8 = (rgb_image * 255).astype(np.uint8)

        np.copyto(frame, rgb_image_uint8)
