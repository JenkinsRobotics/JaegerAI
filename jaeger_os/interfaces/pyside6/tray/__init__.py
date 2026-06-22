"""Tray icon — menu-bar indicator + lifecycle GUI for the Jaeger daemon.

Two layers:

  - :mod:`.base` — pure-Python logic. State machine, glyph mapping,
    menu construction, action dispatch. Unit-tested, no GUI deps.
  - :mod:`.macos` — ``rumps``-backed adapter that wires the logic into
    macOS's menu bar. The daemon-poller timer + the click handlers
    live here.

The tray is deliberately *dumb*: it only ever invokes ``jaeger ...``
subprocesses for lifecycle work. It never imports the agent or the
pipeline. See [[feedback-tray-no-pipeline-logic]] for the rationale —
same constraint Lilith's ``tray.py`` follows.

Cross-platform Linux/Windows backends slot in via the same protocol
when there's a Jaeger unit on those platforms to use them.
"""

from __future__ import annotations

from jaeger_os.interfaces.pyside6.tray.base import (
    MenuItem,
    TrayActions,
    TrayModel,
    TrayState,
    glyph_for,
    icon_path_for,
    menu_items_for,
)

__all__ = [
    "MenuItem", "TrayActions", "TrayModel", "TrayState",
    "glyph_for", "icon_path_for", "menu_items_for",
]
