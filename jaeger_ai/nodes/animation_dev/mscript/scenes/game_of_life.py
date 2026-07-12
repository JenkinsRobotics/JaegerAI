# assets/math/game_of_life.py
# A Python/NumPy implementation of Conway's Game of Life.

import numpy as np
from mscript.mochi_animations import Animation

class GameOfLife(Animation):
    """
    An optimized implementation of Conway's Game of Life using NumPy for fast,
    vectorized calculations.
    """
    name = "game_of_life"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.grid = np.zeros((self.h, self.w), dtype=np.uint8)
        self.last_update_time = 0.0
        self.update_interval = 0.1  # seconds
        self.color_override = (255, 255, 255) # Default to white

    def on_enter(self, **kwargs):
        super().on_enter(**kwargs)
        # Initialize with a random pattern
        self.grid = np.random.choice([0, 1], size=(self.h, self.w), p=[0.8, 0.2])

        if "CLR" in kwargs and isinstance(kwargs["CLR"], list):
            self.color_override = tuple(kwargs["CLR"])

    def on_exit(self):
        # Clear the grid on exit
        self.grid = np.zeros((self.h, self.w), dtype=np.uint8)
        super().on_exit()

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))

        # Update the grid state at the specified interval
        if t - self.last_update_time > self.update_interval:
            self.last_update_time = t
            self.update_grid()

        # Draw the grid using efficient NumPy indexing
        # Set all cells to black first if clearing, otherwise just update
        if self.clear_on_frame:
            frame[:, :] = (0, 0, 0)
        
        live_cells = self.grid == 1
        frame[live_cells] = self.color_override
        
        # Only needed if not clearing the frame, to turn dead cells black
        if not self.clear_on_frame:
            dead_cells = self.grid == 0
            frame[dead_cells] = (0, 0, 0)


    def update_grid(self):
        """
        Updates the grid state according to the rules of Game of Life using
        vectorized NumPy operations for performance.
        """
        # Count live neighbors for each cell using np.roll for toroidal boundaries
        neighbors = (
            np.roll(self.grid, 1, axis=0) +      # Down
            np.roll(self.grid, -1, axis=0) +     # Up
            np.roll(self.grid, 1, axis=1) +      # Right
            np.roll(self.grid, -1, axis=1) +     # Left
            np.roll(np.roll(self.grid, 1, axis=0), 1, axis=1) +  # Down-Right
            np.roll(np.roll(self.grid, 1, axis=0), -1, axis=1) + # Down-Left
            np.roll(np.roll(self.grid, -1, axis=0), 1, axis=1) + # Up-Right
            np.roll(np.roll(self.grid, -1, axis=0), -1, axis=1)  # Up-Left
        )

        # Apply Conway's Game of Life rules:
        # 1. A living cell with 2 or 3 neighbors survives.
        # 2. A dead cell with 3 neighbors becomes alive.
        survive = (self.grid == 1) & ((neighbors == 2) | (neighbors == 3))
        birth = (self.grid == 0) & (neighbors == 3)

        # Update the grid
        self.grid = (survive | birth).astype(np.uint8)
