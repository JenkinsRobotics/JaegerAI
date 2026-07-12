
import numpy as np
from mscript.mochi_animations import Animation

class Eyes(Animation):
    name = "eyes"

    def __init__(self, w: int, h: int):
        super().__init__(w, h)
        self.eye_radius = 12
        self.pupil_radius = 4
        self.eye_y = h // 2
        self.left_eye_x = w // 2 - 18
        self.right_eye_x = w // 2 + 18
        self.pupil_offset_x = 0
        self.pupil_offset_y = 0
        self.is_asleep = True
        self.blink_state = 0  # 0: open, 1: closing, 2: opening
        self.blink_progress = 0.0
        self.blink_speed = 4.0
        self.fg = (255, 255, 255)

    def on_enter(self, **kwargs):
        # The 'FG' argument is now expected as a list of integers.
        fg_color = kwargs.get("FG")
        if fg_color and isinstance(fg_color, list):
            self.fg = tuple(fg_color)

    def on_event(self, event: str, **kwargs):
        event = event.lower()
        if event == "wakeup":
            self.is_asleep = False
        elif event == "sleep":
            self.is_asleep = True
        elif event == "blink":
            if self.blink_state == 0:
                self.blink_state = 1
                self.blink_progress = 0.0
        elif event == "look_left":
            self.pupil_offset_x = -6
        elif event == "look_right":
            self.pupil_offset_x = 6
        elif event == "center":
            self.pupil_offset_x = 0
            self.pupil_offset_y = 0

    def render_into(self, t: float, pixel_buf: bytearray):
        frame = np.frombuffer(pixel_buf, dtype=np.uint8).reshape((self.h, self.w, 3))
        frame[:, :] = (0, 0, 0)  # Clear to black

        if self.is_asleep:
            # Draw closed eyes (lines)
            y = self.eye_y
            for i in range(-self.eye_radius, self.eye_radius):
                frame[y, self.left_eye_x + i] = self.fg
                frame[y, self.right_eye_x + i] = self.fg
            return

        # Handle blinking animation
        if self.blink_state != 0:
            self.blink_progress += self.blink_speed * (1.0/60.0) # Assuming 60fps
            if self.blink_progress >= 1.0:
                if self.blink_state == 1: # Was closing
                    self.blink_state = 2 # Now opening
                    self.blink_progress = 0.0
                elif self.blink_state == 2: # Was opening
                    self.blink_state = 0 # Now open
                    self.blink_progress = 0.0

        # Draw eyes (circles)
        y_coords, x_coords = np.mgrid[0:self.h, 0:self.w]

        # Left eye
        left_eye_mask = (x_coords - self.left_eye_x)**2 + (y_coords - self.eye_y)**2 < self.eye_radius**2
        frame[left_eye_mask] = self.fg

        # Right eye
        right_eye_mask = (x_coords - self.right_eye_x)**2 + (y_coords - self.eye_y)**2 < self.eye_radius**2
        frame[right_eye_mask] = self.fg

        # Draw pupils
        left_pupil_x = self.left_eye_x + self.pupil_offset_x
        left_pupil_y = self.eye_y + self.pupil_offset_y
        left_pupil_mask = (x_coords - left_pupil_x)**2 + (y_coords - left_pupil_y)**2 < self.pupil_radius**2
        frame[left_pupil_mask] = (0, 0, 0)

        right_pupil_x = self.right_eye_x + self.pupil_offset_x
        right_pupil_y = self.eye_y + self.pupil_offset_y
        right_pupil_mask = (x_coords - right_pupil_x)**2 + (y_coords - right_pupil_y)**2 < self.pupil_radius**2
        frame[right_pupil_mask] = (0, 0, 0)

        # Apply blink effect
        if self.blink_state == 1: # Closing
            lid_height = int(self.eye_radius * 2 * self.blink_progress)
            frame[self.eye_y - self.eye_radius : self.eye_y - self.eye_radius + lid_height, :] = (0,0,0)
            frame[self.eye_y + self.eye_radius - lid_height : self.eye_y + self.eye_radius, :] = (0,0,0)
        elif self.blink_state == 2: # Opening
            lid_height = int(self.eye_radius * 2 * (1.0 - self.blink_progress))
            frame[self.eye_y - self.eye_radius : self.eye_y - self.eye_radius + lid_height, :] = (0,0,0)
            frame[self.eye_y + self.eye_radius - lid_height : self.eye_y + self.eye_radius, :] = (0,0,0)
