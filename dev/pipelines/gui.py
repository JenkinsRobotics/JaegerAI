#!/usr/bin/env python3
"""Surfaces pipeline probe.

Launch the dev surface gallery — a window with a button per prealpha
surface (Jaeger Studio, avatar player, media player), so you can open +
eyeball each. (The same gallery the windowed-app tray's "Dev windows…"
opens; this runs it standalone, no agent.)

    .venv/bin/python dev/pipelines/gui.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from jaeger_os.interfaces.gallery.window import GalleryWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = GalleryWindow()
    win.show()
    print("gallery open — click a surface to launch it. Close the window to exit.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
