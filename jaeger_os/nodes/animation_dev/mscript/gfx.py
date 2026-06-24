# core/gfx.py
# A NumPy-based graphics primitive library, inspired by Adafruit GFX.

import numpy as np
from typing import Tuple, Union, List
from .font import FONT_DATA

# --- Color Palette ---
COLORS = {
    "BLACK": (0, 0, 0),
    "RED": (255, 0, 0),
    "GREEN": (0, 255, 0),
    "BLUE": (0, 0, 255),
    "YELLOW": (255, 255, 0),
    "CYAN": (0, 255, 255),
    "MAGENTA": (255, 0, 255),
    "WHITE": (255, 255, 255),
}

def parse_color(color: Union[str, List[int], Tuple[int, int, int]], default: Tuple[int, int, int] = (0,0,0)) -> Tuple[int, int, int]:
    """Parses a color from a string name or a list/tuple of RGB values."""
    if isinstance(color, str):
        return COLORS.get(color.upper(), default)
    if isinstance(color, (list, tuple)) and len(color) == 3:
        return tuple(color)
    return default

# Pre-calculated coordinate grids, cached for performance.
_coord_cache = {}

def _get_coords(w, h):
    if (w, h) in _coord_cache:
        return _coord_cache[(w, h)]
    yy, xx = np.mgrid[0:h, 0:w]
    _coord_cache[(w, h)] = (yy, xx)
    return yy, xx

def draw_line(frame: np.ndarray, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int]):
    h, w, _ = frame.shape
    steep = abs(y1 - y0) > abs(x1 - x0)
    if steep: x0, y0, x1, y1 = y0, x0, y1, x1
    if x0 > x1: x0, x1, y0, y1 = x1, x0, y1, y0
    dx, dy = x1 - x0, abs(y1 - y0)
    err, ystep = dx // 2, 1 if y0 < y1 else -1
    for x in range(x0, x1 + 1):
        if steep:
            if 0 <= x < h and 0 <= y0 < w: frame[x, y0] = color
        else:
            if 0 <= y0 < h and 0 <= x < w: frame[y0, x] = color
        err -= dy
        if err < 0:
            y0 += ystep
            err += dx

def draw_triangle(frame: np.ndarray, x0, y0, x1, y1, x2, y2, color):
    draw_line(frame, x0, y0, x1, y1, color)
    draw_line(frame, x1, y1, x2, y2, color)
    draw_line(frame, x2, y2, x0, y0, color)

def fill_triangle(frame: np.ndarray, x0, y0, x1, y1, x2, y2, color):
    if y0 > y1: x0, x1, y0, y1 = x1, x0, y1, y0
    if y0 > y2: x0, x2, y0, y2 = x2, x0, y2, y0
    if y1 > y2: x1, x2, y1, y2 = x2, x1, y2, y1
    if y0 == y2: return
    if y1 == y2: _fill_flat_bottom_triangle(frame, x0, y0, x1, y1, x2, y2, color)
    elif y0 == y1: _fill_flat_top_triangle(frame, x0, y0, x1, y1, x2, y2, color)
    else:
        x3 = int(x0 + float(y1 - y0) / float(y2 - y0) * (x2 - x0))
        _fill_flat_bottom_triangle(frame, x0, y0, x1, y1, x3, y1, color)
        _fill_flat_top_triangle(frame, x1, y1, x3, y1, x2, y2, color)

def _fill_flat_bottom_triangle(frame, x0, y0, x1, y1, x2, y2, color):
    invslope1 = (x1 - x0) / (y1 - y0) if y1 > y0 else 0
    invslope2 = (x2 - x0) / (y2 - y0) if y2 > y0 else 0
    curx1, curx2 = float(x0), float(x0)
    h, w, _ = frame.shape
    for scanlineY in range(y0, y1 + 1):
        if 0 <= scanlineY < h:
            x_start, x_end = sorted((int(curx1), int(curx2)))
            frame[scanlineY, max(0, x_start):min(w, x_end)] = color
        curx1 += invslope1
        curx2 += invslope2

def _fill_flat_top_triangle(frame, x0, y0, x1, y1, x2, y2, color):
    invslope1 = (x2 - x0) / (y2 - y0) if y2 > y0 else 0
    invslope2 = (x2 - x1) / (y2 - y1) if y2 > y1 else 0
    curx1, curx2 = float(x2), float(x2)
    h, w, _ = frame.shape
    for scanlineY in range(y2, y0 - 1, -1):
        if 0 <= scanlineY < h:
            x_start, x_end = sorted((int(curx1), int(curx2)))
            frame[scanlineY, max(0, x_start):min(w, x_end)] = color
        curx1 -= invslope1
        curx2 -= invslope2

def draw_round_rect(frame, x, y, w, h, r, color):
    draw_line(frame, x + r, y, x + w - r - 1, y, color)
    draw_line(frame, x + r, y + h - 1, x + w - r - 1, y + h - 1, color)
    draw_line(frame, x, y + r, x, y + h - r - 1, color)
    draw_line(frame, x + w - 1, y + r, x + w - 1, y + h - r - 1, color)
    _draw_corner_arc(frame, x + r, y + r, r, 1, color)
    _draw_corner_arc(frame, x + w - r - 1, y + r, r, 2, color)
    _draw_corner_arc(frame, x + w - r - 1, y + h - r - 1, r, 4, color)
    _draw_corner_arc(frame, x + r, y + h - r - 1, r, 8, color)

def fill_round_rect(frame, x, y, w, h, r, color):
    frame[y+r:y+h-r, x:x+w] = color
    frame[y:y+h, x+r:x+w-r] = color
    _fill_corner(frame, x + r, y + r, r, 1, color)
    _fill_corner(frame, x + w - r - 1, y + r, r, 2, color)
    _fill_corner(frame, x + w - r - 1, y + h - r - 1, r, 4, color)
    _fill_corner(frame, x + r, y + h - r - 1, r, 8, color)

def _draw_corner_arc(frame, x_c, y_c, r, corner, color):
    h, w, _ = frame.shape
    yy, xx = _get_coords(w, h)
    dist_sq = (xx - x_c)**2 + (yy - y_c)**2
    mask = (dist_sq >= (r-1)**2) & (dist_sq < r**2)
    if corner == 1: mask &= (xx <= x_c) & (yy <= y_c)
    elif corner == 2: mask &= (xx >= x_c) & (yy <= y_c)
    elif corner == 4: mask &= (xx >= x_c) & (yy >= y_c)
    elif corner == 8: mask &= (xx <= x_c) & (yy >= y_c)
    frame[mask] = color

def _fill_corner(frame, x_c, y_c, r, corner, color):
    h, w, _ = frame.shape
    yy, xx = _get_coords(w, h)
    mask = (xx - x_c)**2 + (yy - y_c)**2 < r**2
    if corner == 1: mask &= (xx <= x_c) & (yy <= y_c)
    elif corner == 2: mask &= (xx >= x_c) & (yy <= y_c)
    elif corner == 4: mask &= (xx >= x_c) & (yy >= y_c)
    elif corner == 8: mask &= (xx <= x_c) & (yy >= y_c)
    frame[mask] = color

def draw_char(frame: np.ndarray, x: int, y: int, char: str, color: Tuple[int, int, int], size: int):
    char_data = FONT_DATA.get(char)
    if not char_data: return

    h, w, _ = frame.shape
    for i, line in enumerate(char_data):
        for j in range(7, -1, -1):
            if (line >> j) & 1:
                px = x + i * size
                py = y + (7-j) * size
                if 0 <= px < w and 0 <= py < h:
                    frame[py:py+size, px:px+size] = color

def draw_text(frame: np.ndarray, x: int, y: int, text: str, color: Tuple[int, int, int], size: int):
    cursor_x, cursor_y = x, y
    h, w, _ = frame.shape
    char_width = 5 * size
    char_height = 7 * size

    for char in text:
        if char == '\n':
            cursor_y += char_height + size # New line
            cursor_x = x
        else:
            if cursor_x + char_width > w:
                cursor_y += char_height + size # Word wrap
                cursor_x = x
            draw_char(frame, cursor_x, cursor_y, char, color, size)
            cursor_x += char_width + size # Advance cursor
