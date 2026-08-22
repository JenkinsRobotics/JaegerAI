"""LED matrix command helpers (port of JP01-CC01/devices/led_matrix.py)."""

from __future__ import annotations


def build_matrix_mode(mode: int) -> str:
    return f"MM[{int(mode)}]"


def build_matrix_brightness(value: int) -> str:
    return f"BM[{int(value)}]"


def build_matrix_frame(rgb_hex: str) -> str:
    """``rgb_hex``: string of RGB hex (6 chars per pixel)."""
    return f"FM[{rgb_hex}]"
