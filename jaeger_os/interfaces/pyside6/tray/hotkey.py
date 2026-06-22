"""Global ⌥Space hotkey via Carbon (ctypes) — the PySide6 twin of the
Swift ``PillHotkey``.

Carbon ``RegisterEventHotKey`` is the canonical macOS shortcut API: it
claims the combo system-wide *without* the Accessibility permission that
``NSEvent`` global monitors / ``CGEventTap`` (pynput) require — so the
PySide6 app matches the Swift app's friction-free behaviour.  pyobjc
doesn't expose the call, so we reach it through ctypes.  Qt's macOS event
loop pumps the same run loop Carbon dispatches on, so a handler installed
on the application event target fires while the app runs.

Degrades gracefully: any failure (non-macOS host, missing framework,
non-zero OSStatus) leaves :meth:`register` returning ``False`` and the
pill still reachable from the tray dropdown's "Quick input…" row.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Callable

# Carbon four-char-code constants.
_kEventClassKeyboard = 0x6B657962      # 'keyb'
_kEventHotKeyPressed = 6
_optionKey = 0x0800                    # Carbon modifier mask (Option/Alt)
_kVK_Space = 49                        # virtual key code for Space
_noErr = 0


def _fourcc(code: str) -> int:
    return (ord(code[0]) << 24) | (ord(code[1]) << 16) \
        | (ord(code[2]) << 8) | ord(code[3])


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


# OSStatus (*)(EventHandlerCallRef, EventRef, void*)
_HANDLER_PROC = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
)


class GlobalHotkey:
    """⌥Space → ``on_fire``. Hold a reference for the app's lifetime."""

    def __init__(self) -> None:
        self._carbon: ctypes.CDLL | None = None
        self._hotkey_ref = ctypes.c_void_p()
        self._handler_ref = ctypes.c_void_p()
        self._proc: object = None        # keep the CFUNCTYPE alive (no GC)
        self._on_fire: Callable[[], None] | None = None

    def register(self, on_fire: Callable[[], None]) -> bool:
        """Claim ⌥Space. Returns True on success, False (no-op) otherwise."""
        path = ctypes.util.find_library("Carbon")
        if not path:
            return False
        try:
            carbon = ctypes.cdll.LoadLibrary(path)
        except OSError:
            return False
        self._carbon = carbon
        self._on_fire = on_fire

        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        target = carbon.GetApplicationEventTarget()
        if not target:
            return False

        def _trampoline(_call_ref, _event_ref, _user_data):  # main-thread
            try:
                if self._on_fire is not None:
                    self._on_fire()
            except Exception:  # noqa: BLE001 — a UI slip must not crash Carbon
                pass
            return _noErr

        self._proc = _HANDLER_PROC(_trampoline)

        spec = _EventTypeSpec(_kEventClassKeyboard, _kEventHotKeyPressed)
        carbon.InstallEventHandler.argtypes = [
            ctypes.c_void_p, _HANDLER_PROC, ctypes.c_uint32,
            ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.InstallEventHandler.restype = ctypes.c_int32
        if carbon.InstallEventHandler(
            target, self._proc, 1, ctypes.byref(spec), None,
            ctypes.byref(self._handler_ref),
        ) != _noErr:
            return False

        hk_id = _EventHotKeyID(_fourcc("JROS"), 1)
        carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
            ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.RegisterEventHotKey.restype = ctypes.c_int32
        if carbon.RegisterEventHotKey(
            _kVK_Space, _optionKey, hk_id, target, 0,
            ctypes.byref(self._hotkey_ref),
        ) != _noErr:
            return False
        return True

    def unregister(self) -> None:
        if self._carbon is not None and self._hotkey_ref:
            try:
                self._carbon.UnregisterEventHotKey(self._hotkey_ref)
            except Exception:  # noqa: BLE001
                pass
        self._hotkey_ref = ctypes.c_void_p()
        self._on_fire = None
