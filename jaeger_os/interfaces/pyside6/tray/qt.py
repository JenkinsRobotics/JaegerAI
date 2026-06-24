"""Qt menu-bar tray — the always-on surface of the windowed app.

A thin ``QSystemTrayIcon`` adapter (a chassis ``make_surface(ctx, spec)``
surface). Left-click pops the floating Pill quick-launcher; the menu opens
the full chat window or quits. Submitting from the Pill opens the chat
window and renders the message there, so the user bubble is consistent
with a typed one.

Thin by design (the GUI/logic-separation rule): the chassis owns the app /
bus / core; this surface only shows windows and publishes nothing the chat
window doesn't. Lilith's persona/voice menus + global hotkey are runtime
logic JROS doesn't expose on the chassis bus yet — deliberately omitted.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .base import TrayState, asset_path, icon_path_for


def apply_app_icon() -> None:
    """Set the windowed app's icon (every window + the macOS Dock) to the
    ``jaeger_app_icon`` asset. Qt's ``setWindowIcon`` covers windows; the
    Dock for a non-bundled process needs AppKit. Both are best-effort."""
    path = asset_path("jaeger_app_icon.png")
    if not path:
        return
    app = QApplication.instance()
    if app is not None:
        app.setWindowIcon(QIcon(path))
    try:
        from AppKit import NSApplication, NSImage
        img = NSImage.alloc().initByReferencingFile_(path)
        if img is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:  # noqa: BLE001 — non-macOS / pyobjc missing
        pass


def _agent_name(ctx: Any) -> str:
    return (getattr(getattr(ctx, "core", None), "agent_name", None)
            or getattr(ctx, "agent_name", None) or "JROS")


def _subtitle(ctx: Any) -> str:
    """Header subtitle — the model the agent is running, else a generic."""
    core = getattr(ctx, "core", None)
    for attr in ("model_name", "model"):
        val = getattr(core, attr, None)
        if isinstance(val, str) and val:
            return val
    return "Local agent"


class QtTray:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._pill: Any = None
        self._menu: Any = None
        self._settings: Any = None
        self._studio: Any = None
        self._gallery: Any = None
        self._state = "idle"

        # Brand the app — window + macOS Dock icon (the tray is the
        # always-on surface, so this lands even before a window opens).
        apply_app_icon()
        self._name = _agent_name(ctx)
        self._subtitle = _subtitle(ctx)

        # The J menu-bar icon (jaeger_icon.png). Qt scales the high-res
        # PNG to the menu-bar slot. Falls back to a solid square only if
        # the assets dir is missing (stripped install).
        path = icon_path_for(TrayState.RUNNING)
        if path:
            self._icon = QSystemTrayIcon(QIcon(path))
        else:
            pix = QPixmap(18, 18)
            pix.fill(QColor("#1e88e5"))
            self._icon = QSystemTrayIcon(QIcon(pix))
        self._icon.setToolTip(f"JROS — {self._name}")

        # Clicking the icon shows the rich dropdown (no native QMenu — a
        # context menu would intercept the click before our popup).
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

        # Live agent status for the dropdown's status row. The one
        # sanctioned bus→Qt hop (same QObject bridge the chat window uses).
        bus = getattr(ctx, "bus", None)
        self._bridge = None
        if bus is not None:
            from jaeger_os.app.surfaces import make_bus_bridge
            self._bridge = make_bus_bridge(bus, ["/sense/agent_state"])
            self._bridge.message.connect(self._on_state)

        # ⌥Space → the floating pill (the J click shows the dropdown, the
        # shortcut shows the pill — matching the Swift app). Degrades to a
        # no-op if Carbon registration fails; the dropdown still reaches it.
        self._hotkey = None
        try:
            from jaeger_os.interfaces.pyside6.tray.hotkey import GlobalHotkey
            hk = GlobalHotkey()
            if hk.register(self._toggle_pill):
                self._hotkey = hk
        except Exception:  # noqa: BLE001 — hotkey is a nicety, never fatal
            self._hotkey = None

    # ── activation ────────────────────────────────────────────────
    def _on_activated(self, reason: Any) -> None:  # noqa: ARG002 — any click
        self._show_menu()

    def _show_menu(self) -> None:
        from jaeger_os.interfaces.pyside6.tray.menu import TrayMenu
        if self._menu is None:
            self._menu = TrayMenu(
                agent_name=self._name,
                instance_name=self._subtitle,
                on_quick_input=self._show_pill,
                on_open_chat=self._open_chat,
                on_open_studio=self._open_studio,
                on_open_windows=self._open_windows,
                on_quit=self._quit,
                on_settings=self._open_settings,
            )
        self._menu.set_state(self._state)
        self._menu.popup_under(self._icon.geometry())

    def _open_settings(self) -> None:
        from jaeger_os.interfaces.pyside6.settings import open_settings
        # Hold the ref so the window isn't garbage-collected on return.
        self._settings = open_settings()

    def _on_state(self, msg: Any) -> None:
        state = getattr(msg, "state", None)
        if not state:
            return
        self._state = state
        if self._menu is not None:
            self._menu.set_state(state)

    # ── Pill quick-launcher ───────────────────────────────────────
    def _toggle_pill(self) -> None:
        """⌥Space: show the pill, or hide it if it's already up."""
        if self._pill is not None and self._pill.isVisible():
            self._pill.hide()
        else:
            self._show_pill()

    def _show_pill(self) -> None:
        if self._pill is None:
            from jaeger_os.interfaces.pyside6.pill.qt import Pill
            self._pill = Pill(on_submit=self._submit_from_pill,
                              agent_name=self._name,
                              on_open_chat=self._open_chat)
        self._pill.popup()

    def _submit_from_pill(self, text: str) -> None:
        win = self._open_chat()
        submit = getattr(win, "submit_external", None)
        if callable(submit):
            submit(text)

    # ── chat window ───────────────────────────────────────────────
    def _open_chat(self) -> Any:
        """Show + raise the chat window (found among the process's top-level
        widgets) and return it. Returns None if it isn't up yet."""
        win = getattr(self.ctx, "window", None) or self._find_chat_window()
        if win is not None:
            win.show()
            win.raise_()
            win.activateWindow()
        return win

    @staticmethod
    def _find_chat_window() -> Any:
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "submit_external"):   # the ChatWindow
                return w
        return None

    # ── Jaeger Studio + dev windows ───────────────────────────────
    def _open_studio(self) -> Any:
        """Open Jaeger Studio (the multi-tab desktop shell) wired to the
        app's bus + core, so its chat / avatar are live."""
        try:
            from jaeger_os.interfaces.studio.window import make_surface
            self._studio = make_surface(self.ctx)
            self._studio.show(); self._studio.raise_(); self._studio.activateWindow()
            return self._studio
        except Exception as exc:  # noqa: BLE001
            self._warn("Jaeger Studio", exc)
            return None

    def _open_windows(self) -> Any:
        """Open the surface gallery — a launcher for the prealpha windows
        (Studio, avatar player, media player) so each can be tested."""
        try:
            from jaeger_os.interfaces.gallery.window import GalleryWindow
            self._gallery = GalleryWindow(self.ctx)
            self._gallery.show(); self._gallery.raise_(); self._gallery.activateWindow()
            return self._gallery
        except Exception as exc:  # noqa: BLE001
            self._warn("Dev windows", exc)
            return None

    @staticmethod
    def _warn(what: str, exc: Exception) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, f"{what} failed", f"{type(exc).__name__}: {exc}")

    # ── lifecycle ─────────────────────────────────────────────────
    def _quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def close(self) -> None:
        for widget in (self._pill, self._menu, self._settings,
                       self._studio, self._gallery):
            if widget is not None:
                try:
                    widget.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._bridge is not None:
            try:
                self._bridge.close()
            except Exception:  # noqa: BLE001
                pass
        if self._hotkey is not None:
            try:
                self._hotkey.unregister()
            except Exception:  # noqa: BLE001
                pass
        self._icon.hide()


def make_surface(ctx: Any, spec: Any = None) -> QtTray:  # noqa: ARG001
    return QtTray(ctx)
