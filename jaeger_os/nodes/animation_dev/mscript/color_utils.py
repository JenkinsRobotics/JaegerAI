# core/color_utils.py

"""
Color Utility: A centralized helper for color parsing and manipulation.
"""

from typing import Tuple, Union, List

# A mapping of common color names to their RGB values.
COLOR_MAP = {
    "BLACK": (0, 0, 0),
    "WHITE": (255, 255, 255),
    "RED": (255, 0, 0),
    "GREEN": (0, 255, 0),
    "BLUE": (0, 0, 255),
    "YELLOW": (255, 255, 0),
    "CYAN": (0, 255, 255),
    "MAGENTA": (255, 0, 255),
}

def parse_color(color_val: Union[str, Tuple[int, int, int], List[int]], default: Tuple[int, int, int] = (255, 255, 255)) -> Tuple[int, int, int]:
    """
    Parses a color value from a script argument into a standard RGB tuple.

    Args:
        color_val: The color value to parse. It can be:
                   - A string color name (e.g., "RED").
                   - A space-separated RGB string (e.g., "0 255 0").
                   - A list or tuple of RGB integers (e.g., [0, 255, 0]).
        default: The default color to return if parsing fails.

    Returns:
        An RGB tuple (r, g, b).
    """
    if isinstance(color_val, (tuple, list)) and len(color_val) == 3:
        return tuple(color_val)
    
    if isinstance(color_val, str):
        color_str = color_val.upper()
        if color_str in COLOR_MAP:
            return COLOR_MAP[color_str]
        try:
            # Try parsing space-separated string "r g b"
            return tuple(map(int, color_str.split()))
        except (ValueError, AttributeError):
            pass # Fall through to default

    return default
