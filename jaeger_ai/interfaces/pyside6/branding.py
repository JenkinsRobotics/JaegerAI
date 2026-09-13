"""One desktop identity for native-app helpers and standalone Qt faces."""

from __future__ import annotations

import logging
import os
import sys

from .tray.base import asset_path

APP_NAME = "Jaeger AI"
BUNDLE_ID = "com.jenkinsrobotics.JaegerAI"


def apply_app_identity(window=None) -> None:
    """Brand every entry point, including faces launched without the Qt tray.

    Native-app helpers are accessory processes: the parent owns the single
    Dock entry. Standalone Qt apps retain their own correctly branded entry.
    Offscreen tests never initialize AppKit or a desktop graphics context.
    """
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(BUNDLE_ID)
    path = asset_path("jaeger_app_icon.png")
    if not path:
        raise RuntimeError("Jaeger AI desktop icon is missing from the installation")
    icon = app.windowIcon()
    if app.property("jaegerDesktopIcon") != path or icon.isNull():
        icon = QIcon(path)
        if icon.isNull():
            raise RuntimeError(f"Invalid Jaeger AI desktop icon: {path}")
        app.setWindowIcon(icon)
        app.setProperty("jaegerDesktopIcon", path)
    if window is not None:
        window.setWindowIcon(icon)
    if sys.platform == "darwin" and app.platformName() == "cocoa":
        try:
            from AppKit import NSApplication, NSImage

            native = NSApplication.sharedApplication()
            native.setApplicationIconImage_(NSImage.alloc().initByReferencingFile_(path))
            if os.environ.get("JAEGER_DESKTOP_HELPER") == "1":
                native.setActivationPolicy_(1)  # accessory; no duplicate Dock tile
        except ImportError:
            logging.getLogger(__name__).warning("AppKit desktop integration unavailable")
