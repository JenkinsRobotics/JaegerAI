"""NeoPixel command helpers (port of JP01-CC01/devices/neopixel.py)."""

from __future__ import annotations


def build_neopixel_mode(mode: int) -> str:
    return f"MN[{int(mode)}]"


def build_neopixel_frame(wrgb_hex: str) -> str:
    """``wrgb_hex``: string of WRGB hex (8 chars per LED)."""
    return f"FN[{wrgb_hex}]"
