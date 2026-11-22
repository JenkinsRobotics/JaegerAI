"""Tiny CoreAudio helper (ctypes): enumerate and select real audio devices.

Droid mode speaks through a chosen speaker (the Mac Studio's own by default)
even when another app, such as a remote-desktop audio driver, has taken the
system default output. Droid scopes both defaults to its chosen hardware while
AVAudioEngine creates the graph, then immediately restores the operator route.
"""
from __future__ import annotations

import ctypes
import struct

_CA = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
_CF = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_CF.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
_CF.CFStringGetCString.restype = ctypes.c_bool
_CF.CFRelease.argtypes = [ctypes.c_void_p]


def _cc(code: str) -> int:
    return struct.unpack(">I", code.encode())[0]


class _Address(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


SYSTEM = 1
GLOBAL, OUTPUT, INPUT = _cc("glob"), _cc("outp"), _cc("inpt")
DEVICES, NAME, STREAMS = _cc("dev#"), _cc("lnam"), _cc("stm#")
DEFAULT_OUTPUT, DEFAULT_INPUT, SYSTEM_OUTPUT = _cc("dOut"), _cc("dIn "), _cc("sOut")


def _size(obj: int, selector: int, scope: int = GLOBAL) -> int:
    addr, size = _Address(selector, scope, 0), ctypes.c_uint32(0)
    if _CA.AudioObjectGetPropertyDataSize(obj, ctypes.byref(addr), 0, None, ctypes.byref(size)):
        return 0
    return size.value


def _get(obj: int, selector: int, buf, scope: int = GLOBAL) -> bool:
    addr, size = _Address(selector, scope, 0), ctypes.c_uint32(ctypes.sizeof(buf))
    return _CA.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(buf)) == 0


def device_name(device: int) -> str:
    ref = ctypes.c_void_p()
    if not _get(device, NAME, ref) or not ref.value:
        return ""
    out = ctypes.create_string_buffer(512)
    ok = _CF.CFStringGetCString(ref, out, 512, 0x08000100)  # UTF-8
    _CF.CFRelease(ref)
    return out.value.decode("utf-8", "replace") if ok else ""


def devices() -> list[dict]:
    count = _size(SYSTEM, DEVICES) // 4
    ids = (ctypes.c_uint32 * max(count, 1))()
    if not count or not _get(SYSTEM, DEVICES, ids):
        return []
    return [{"id": int(d), "name": device_name(d),
             "output": _size(d, STREAMS, OUTPUT) > 0, "input": _size(d, STREAMS, INPUT) > 0}
            for d in ids[:count]]


def default_device(output: bool = True) -> int:
    value = ctypes.c_uint32(0)
    _get(SYSTEM, DEFAULT_OUTPUT if output else DEFAULT_INPUT, value)
    return int(value.value)


def set_default_device(device: int, output: bool = True) -> bool:
    addr = _Address(DEFAULT_OUTPUT if output else DEFAULT_INPUT, GLOBAL, 0)
    value = ctypes.c_uint32(device)
    return _CA.AudioObjectSetPropertyData(SYSTEM, ctypes.byref(addr), 0, None, 4, ctypes.byref(value)) == 0


def find(name: str, output: bool = True) -> int:
    """Device id whose name matches ``name`` (exact, then case-insensitive prefix); 0 if none."""
    wanted = (name or "").strip().lower()
    rows = [d for d in devices() if d["output" if output else "input"]]
    for d in rows:
        if d["name"].lower() == wanted:
            return d["id"]
    for d in rows:
        if wanted and d["name"].lower().startswith(wanted):
            return d["id"]
    return 0


# Virtual / loopback outputs that cannot reliably start AVAudioEngine, including
# leftover remote-desktop devices such as Jump Desktop Audio.
VIRTUAL_OUTPUT_MARKERS = (
    "jump desktop", "blackhole", "loopback", "soundflower", "aggregate",
    "multi-output", "multi output", "virtual", "dummy", "zoomaudiodevice",
    "microsoft teams audio", "webex", "discord",
)


def is_virtual_output(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return any(marker in lowered for marker in VIRTUAL_OUTPUT_MARKERS)


def real_outputs() -> list[dict]:
    """Output devices that are safe to speak through, built-in speakers first."""
    rows = [device for device in devices() if device["output"] and not is_virtual_output(device["name"])]

    def rank(device: dict) -> tuple[int, str]:
        name = device["name"].lower()
        if "mac studio speakers" in name or "built-in" in name:
            return (0, name)
        if "speakers" in name:
            return (1, name)
        return (2, name)

    return sorted(rows, key=rank)


def pick_output(preferred: str = "") -> tuple[int, str, str]:
    """Return ``(device_id, name, note)`` for the preferred real speaker, or a fallback.

    ``note`` is empty when the preferred device was used; otherwise it explains
    the fallback. Returns ``(0, "", reason)`` when no real speaker exists.
    """
    rows = real_outputs()
    if not rows:
        current = device_name(default_device(True)) or "unknown"
        return 0, "", f"No real speaker is available (default output is {current})"
    wanted = find(preferred) if preferred else 0
    for device in rows:
        if device["id"] == wanted or (preferred and device["name"].lower() == preferred.strip().lower()):
            return device["id"], device["name"], ""
    chosen = rows[0]
    wanted_name = (preferred or "").strip() or "the configured speaker"
    return chosen["id"], chosen["name"], f"Using {chosen['name']} because {wanted_name} was not available"


def pick_input(preferred: str = "") -> tuple[int, str, str]:
    """Return an explicit microphone, preferring the configured device then the system default."""
    rows = [device for device in devices() if device["input"]]
    if not rows:
        return 0, "", "No microphone is available"
    wanted = find(preferred, output=False) if preferred else 0
    for device in rows:
        if device["id"] == wanted:
            return device["id"], device["name"], ""
    current = default_device(False)
    for device in rows:
        if device["id"] == current:
            wanted_name = (preferred or "").strip() or "the configured microphone"
            return device["id"], device["name"], (
                f"Using {device['name']} because {wanted_name} was not available"
            )
    chosen = rows[0]
    return chosen["id"], chosen["name"], f"Using {chosen['name']} because no default microphone was available"


if __name__ == "__main__":
    import json
    print(json.dumps({"devices": devices(), "default_output": device_name(default_device(True)),
                      "default_input": device_name(default_device(False)),
                      "real_outputs": real_outputs()}, indent=2))
