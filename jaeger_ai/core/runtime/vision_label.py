"""Deterministic high-contrast label codec for vision fixtures.

Encodes ASCII tokens as a 5x7 bitmap in the top rows of a PNG. Jaeger reads
the pixels; the token is not placed in metadata.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

_FONT = {
    "0": "01110100011001110101110011000101110",
    "1": "00100011000010000100001000010001110",
    "2": "01110100010000100110010001000011111",
    "3": "01110100010000100110000011000101110",
    "4": "00010001100010101001111100010000100",
    "5": "11111100001111000001000011000101110",
    "6": "00110010001000011110100011000101110",
    "7": "11111000010001000100001000010000100",
    "8": "01110100011000101110100011000101110",
    "9": "01110100011000101111000010001001100",
    "A": "01110100011111110001100011000110001",
    "B": "11110100011111010001100011000111110",
    "C": "01110100011000010000100001000101110",
    "D": "11100100011000110001100011000111100",
    "E": "11111100001110010000100001000011111",
    "F": "11111100001110010000100001000010000",
    "G": "01110100011000010111100011000101111",
    "H": "10001100011111110001100011000110001",
    "I": "01110001000010000100001000010001110",
    "J": "00001000010000100001100011000101110",
    "K": "10001100101010011000101001001010001",
    "L": "10000100001000010000100001000011111",
    "M": "10001110111010110001100011000110001",
    "N": "10001110011010110011100011000110001",
    "O": "01110100011000110001100011000101110",
    "P": "11110100011000111110100001000010000",
    "Q": "01110100011000110001100101001001101",
    "R": "11110100011000111110101001001010001",
    "S": "01111100000111000001000011000111110",
    "T": "11111001000010000100001000010000100",
    "U": "10001100011000110001100011000101110",
    "V": "10001100011000110001100010101000100",
    "W": "10001100011000110001101011101110001",
    "X": "10001100010101000100010101000110001",
    "Y": "10001100010101000100001000010000100",
    "Z": "11111000010001000100010001000011111",
    "-": "00000000000000011111000000000000000",
}


def _png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b""
    stride = width * 3
    for y in range(height):
        raw += b"\x00" + pixels[y * stride:(y + 1) * stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def encode_label_png(token: str, *, scale: int = 8) -> bytes:
    token = "".join(ch for ch in str(token).upper() if ch in _FONT)
    if not token:
        raise ValueError("token has no encodable characters")
    cols = 6 * len(token)
    width = cols * scale
    height = 9 * scale
    pixels = bytearray(width * height * 3)
    for i, ch in enumerate(token):
        bits = _FONT[ch]
        for y in range(7):
            for x in range(5):
                on = bits[y * 5 + x] == "1"
                color = (0, 0, 0) if on else (255, 255, 255)
                for dy in range(scale):
                    for dx in range(scale):
                        px = (i * 6 + x) * scale + dx
                        py = (y + 1) * scale + dy
                        off = (py * width + px) * 3
                        pixels[off:off + 3] = bytes(color)
    return _png(width, height, bytes(pixels))


def decode_label_png(path: str | Path) -> str | None:
    data = Path(path).read_bytes()
    if not data.startswith(b"\x89PNG"):
        return None
    pos = 8
    width = height = None
    raw = b""
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height = struct.unpack(">II", chunk[:8])
        elif tag == b"IDAT":
            raw += chunk
        elif tag == b"IEND":
            break
    if not width or not height:
        return None
    body = zlib.decompress(raw)
    stride = width * 3 + 1
    if len(body) < stride * height:
        return None
    scale = max(1, height // 9)
    cols = width // (6 * scale)
    if cols <= 0:
        return None
    bits_by_glyph = {v: k for k, v in _FONT.items()}
    out = []
    for i in range(cols):
        bits = []
        for y in range(7):
            for x in range(5):
                px = (i * 6 + x) * scale + scale // 2
                py = (y + 1) * scale + scale // 2
                off = py * stride + 1 + px * 3
                if off + 3 > len(body):
                    bits.append("0")
                    continue
                r, g, b = body[off], body[off + 1], body[off + 2]
                bits.append("1" if r + g + b < 384 else "0")
        glyph = "".join(bits)
        ch = bits_by_glyph.get(glyph)
        if ch:
            out.append(ch)
    token = "".join(out).strip("-")
    return token or None
