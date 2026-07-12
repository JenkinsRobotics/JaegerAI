
import time
import numpy as np
from mscript.mochi_animations import Animation

class Timer(Animation):
    name = "timer"

    # 3x5 font for digits 0-9
    DIGITS = [
        [0x1F, 0x11, 0x1F],  # 0
        [0x00, 0x1F, 0x00],  # 1
        [0x1D, 0x15, 0x17],  # 2
        [0x15, 0x15, 0x1F],  # 3
        [0x07, 0x04, 0x1F],  # 4
        [0x17, 0x15, 0x1D],  # 5
        [0x1F, 0x15, 0x1D],  # 6
        [0x01, 0x01, 0x1F],  # 7
        [0x1F, 0x15, 0x1F],  # 8
        [0x17, 0x15, 0x1F],  # 9
    ]

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.countdown_end_time = 0
        self.timer_running = False
        self.fg = (255, 255, 255)  # Default to white
        self.initial_display_time = 0.0 # New: Store initial time for display

    def on_enter(self, **kwargs):
        # The 'FG' argument is now expected as a list of integers.
        fg_color = kwargs.get("FG")
        if fg_color and isinstance(fg_color, list):
            self.fg = tuple(fg_color)
        
        # New: Handle initial display time 'D'
        initial_time_d = kwargs.get("D")
        if initial_time_d is not None:
            try:
                self.initial_display_time = float(initial_time_d)
            except ValueError:
                print(f"Warning: Could not parse initial time D: {initial_time_d}")

    def on_event(self, event: str, **kwargs):
        if event.lower() == "start":
            # Use the standard 'DUR_M' argument key
            duration_mins = int(kwargs.get("DUR_M", 0))
            if duration_mins > 0:
                self.countdown_end_time = time.time() + duration_mins * 60
                self.timer_running = True

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        frame[:, :] = (0, 0, 0)  # Clear to black

        minutes = 0
        seconds = 0

        if self.timer_running:
            remaining_time = self.countdown_end_time - time.time()
            if remaining_time <= 0:
                remaining_time = 0
                self.timer_running = False

            minutes = int(remaining_time / 60)
            seconds = int(remaining_time % 60)
        elif self.initial_display_time > 0: # New: Display initial time if timer not running
            minutes = int(self.initial_display_time / 60)
            seconds = int(self.initial_display_time % 60)

        self._draw_timer(frame, minutes, seconds)

    def _draw_timer(self, frame, minutes, seconds):
        # Position the timer on the screen
        start_x = 10 # Centered a bit more
        start_y = 28 # Centered a bit more
        digit_spacing = 6

        # Draw minutes
        self._draw_digit(frame, start_x, start_y, minutes // 10, self.fg)
        self._draw_digit(frame, start_x + digit_spacing, start_y, minutes % 10, self.fg)

        # Draw separator (colon)
        colon_x = start_x + 2 * digit_spacing + 1 # Adjusted for spacing
        frame[start_y + 1, colon_x] = self.fg
        frame[start_y + 3, colon_x] = self.fg

        # Draw seconds
        self._draw_digit(frame, start_x + 3 * digit_spacing, start_y, seconds // 10, self.fg)
        self._draw_digit(frame, start_x + 4 * digit_spacing, start_y, seconds % 10, self.fg)

    def _draw_digit(self, frame, x, y, digit, color):
        if not (0 <= digit <= 9):
            return
        
        digit_pattern = self.DIGITS[digit]
        for i in range(3):
            for j in range(5):
                if (digit_pattern[i] >> j) & 1:
                    if 0 <= (y + j) < self.h and 0 <= (x + i) < self.w:
                        frame[y + j, x + i] = color
