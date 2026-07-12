# core/mochi_animations.py

from abc import ABC, abstractmethod
from typing import List, Dict, Any, NamedTuple


# ── shared utilities expected by individual animation scripts ─────
# Six math scripts (face.py, face_2.py, test_filled_round_rects.py,
# test_filled_triangles.py, test_round_rects.py, test_triangles.py)
# import ``clamp8`` from this module.  Without it they all crash at
# import time with: cannot import name 'clamp8'.  Tiny utility, no
# external dep — defined once here, exported via the module
# namespace.

def clamp8(value) -> int:
    """Clamp a numeric value to the unsigned-byte range [0, 255] and
    return it as an int.  Used by colour-math scripts that compute
    channel values in float space and need to land them on the
    pixel buffer."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


# --- Base class for all Commands ---
class Command(NamedTuple):
    """A simple structure for what the node should do."""
    name: str
    args: Dict[str, Any]

# --- Abstract Base Class for all Scripts ---
class Script(ABC):
    """
    Abstract base class for a runnable script.
    A script is an object that returns commands for the node to execute
    based on the current time.
    """
    def __init__(self, path: str):
        import time
        self.path = path
        self.start_time = time.time()

    @abstractmethod
    def update(self, t: float) -> List[Command]:
        """
        Given the current time `t`, return a list of any commands
        that are due to be executed.
        """
        raise NotImplementedError

# --- Abstract Base Class for all Animations ---
class Animation(ABC):
    """
    Abstract base class for a renderable animation.
    An animation is an object that can render its state into a pixel buffer.
    """
    name: str | None = None

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.clear_on_frame = True

    def on_enter(self, **kwargs) -> None:
        """Called when the animation is first activated."""
        pass

    def on_event(self, event: str, **kwargs) -> None:
        """Called when the animation receives a script event."""
        pass

    def set_size(self, w: int, h: int):
        """Called when the logical display size changes."""
        self.w = w
        self.h = h

    @abstractmethod
    def render_into(self, t: float, pixel_buf: bytearray):
        """
        Given the current time `t`, render the animation state into the
        provided pixel buffer.
        """
        raise NotImplementedError
