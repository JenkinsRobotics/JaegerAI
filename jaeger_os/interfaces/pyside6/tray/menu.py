"""Tray dropdown — the rich menu-bar popup (avatar · name · live status).

Clicking the J menu-bar icon shows this card instead of a plain text menu:
a header (the agent's avatar + name + instance) over an **agent-status
row** that mirrors the live ``/sense/agent_state`` — standing by, in deep
thought, error — then the quick actions.  Modelled on the UniFi/macOS
menu-bar dropdown the operator referenced.

Pure UI: the tray owns the bus subscription and pushes state in via
:meth:`TrayMenu.set_state`.  The avatar is the brand J today; a future
pass swaps in the agent's digital avatar (same slot, same size).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QByteArray, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor, QIcon, QPainter, QPainterPath, QPixmap, QPolygon,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .base import TrayState, asset_path, icon_path_for

# The card avatar — the agent's face (a future pass swaps in the live
# digital avatar). Falls back to the brand J if the asset is stripped.
_AVATAR_ASSET = "agent.jpg"

# state → (row text, dot colour).  Words match how the operator describes
# it: "standing by", "in deep thought".  Unknown states show verbatim.
_STATE_DISPLAY: dict[str, tuple[str, str]] = {
    "idle": ("Standing by", "#34C759"),          # green
    "thinking": ("In deep thought…", "#FF9F0A"),  # amber
    "error": ("Something went wrong", "#FF3B30"),  # red
    "stopped": ("Offline", "#8E8E93"),            # grey
}
_DEFAULT_DOT = "#8E8E93"

# Monochrome line icons for the header row (chat · avatar · settings).
_ICON_SVG = {
    "chat": '<path d="M20 14a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/>',
    "avatar": ('<circle cx="12" cy="8" r="3.4"/>'
               '<path d="M5 20c0-3.5 3-5.6 7-5.6s7 2.1 7 5.6"/>'),
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 13a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0'
        '-2.9 1.2V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-2.9-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1'
        'A1.7 1.7 0 0 0 4.6 14H4a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.1-2.9l-.1-.1a2 2 0 1 1 2.8-2.8'
        'l.1.1a1.7 1.7 0 0 0 2.9-1.1V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 2.9 1.1l.1-.1a2 2 0 1 1 2.8 2.8'
        'l-.1.1a1.7 1.7 0 0 0-.4 1.9z"/>'),
    "power": '<path d="M18.4 6.6a9 9 0 1 1-12.77 0"/><path d="M12 2v10"/>',
    "input": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
}
_ICON_WRAP = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
              'stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
              'stroke-linejoin="round">{paths}</svg>')


def _svg_icon(name: str, color: str = "#8E8E93", size: int = 18) -> QIcon:
    svg = _ICON_WRAP.format(color=color, paths=_ICON_SVG[name])
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


def _circular_pixmap(src_path: str, size: int) -> QPixmap:
    """Clip ``src_path`` to a circle at ``size`` px — the avatar slot."""
    src = QPixmap(src_path).scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, src)
    painter.end()
    return out


class TrayMenu(QWidget):
    """Frameless dropdown card. Dismisses on focus loss."""

    def __init__(self, *, agent_name: str, avatar_path: str | None = None,
                 on_quick_input: Callable[[], None],
                 on_open_chat: Callable[[], None],
                 on_quit: Callable[[], None],
                 on_restart: Callable[[], None] | None = None,
                 on_open_companion: Callable[[], None] | None = None,
                 on_settings: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_open_chat = on_open_chat
        self._on_open_companion = on_open_companion
        self._on_quick_input = on_quick_input
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._on_restart = on_restart
        self._caret_x = 160  # updated by popup_under() to point at the tray icon
        self._can_dismiss = False  # grace flag: no click-away close during open
        self._click_filter_installed = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(320)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 15, 12, 12)  # top room for the caret

        card = QFrame()
        card.setObjectName("MenuCard")
        card.setStyleSheet(_STYLE)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(28)
        shadow.setColor(Qt.GlobalColor.black)
        shadow.setOffset(0, 6)
        card.setGraphicsEffect(shadow)

        body = QVBoxLayout(card)
        body.setContentsMargins(14, 14, 14, 10)
        body.setSpacing(10)

        body.addLayout(self._header(agent_name, avatar_path))
        body.addWidget(self._action_bar())   # chat · agent · quick-input

        outer.addWidget(card)
        self.set_state("idle")

    # ── sections ──────────────────────────────────────────────────
    def _header(self, agent_name: str, avatar_path: str | None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        avatar = QLabel()
        avatar.setObjectName("Avatar")
        avatar.setFixedSize(40, 40)
        path = avatar_path or asset_path(_AVATAR_ASSET) or icon_path_for(TrayState.RUNNING)
        if path:
            avatar.setPixmap(_circular_pixmap(str(path), 40))
        self._avatar_label = avatar
        row.addWidget(avatar)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(agent_name)
        name.setObjectName("Name")
        self._name_label = name
        text.addWidget(name)
        # status replaces the old subtitle: dot + live state, set by set_state().
        status = QHBoxLayout()
        status.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setObjectName("StatusDot")
        self._state_label = QLabel("Standing by")
        self._state_label.setObjectName("StatusState")
        status.addWidget(self._dot)
        status.addWidget(self._state_label)
        status.addStretch(1)
        text.addLayout(status)
        row.addLayout(text)
        row.addStretch()

        row.addWidget(self._icon_btn("settings", "Settings", self._open_settings))
        row.addWidget(self._icon_btn("power", "Power — restart / quit", self._power))
        return row

    def _action_bar(self) -> QFrame:
        """The row that used to show Agent Status — now the launcher icons:
        chat · agent, with quick-input on the far right."""
        frame = QFrame()
        frame.setObjectName("ActionCard")
        h = QHBoxLayout(frame)
        h.setContentsMargins(10, 7, 10, 7)
        h.setSpacing(4)
        h.addWidget(self._icon_btn("chat", "Open chat window", self._open_chat))
        if self._on_open_companion is not None:
            h.addWidget(self._icon_btn("avatar", "Agent — avatar + chat",
                                       self._open_companion))
        h.addStretch(1)
        h.addWidget(self._icon_btn("input", "Quick input", self._quick_input))
        return frame

    def _quick_input(self) -> None:
        self.hide()
        self._on_quick_input()

    def _icon_btn(self, name: str, tooltip: str,
                  slot: Callable[[], None]) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("IconBtn")
        btn.setIcon(_svg_icon(name))
        btn.setIconSize(QSize(18, 18))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFlat(True)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        return btn

    def _open_settings(self) -> None:
        self.hide()
        if self._on_settings is not None:
            self._on_settings()

    def _open_chat(self) -> None:
        self.hide()
        self._on_open_chat()

    def _open_companion(self) -> None:
        self.hide()
        if self._on_open_companion is not None:
            self._on_open_companion()

    def _power(self) -> None:
        """Power icon → restart or quit the agent/app."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        if self._on_restart is not None:
            menu.addAction("Restart", lambda: (self.hide(), self._on_restart()))
        menu.addAction("Quit JROS", lambda: (self.hide(), self._on_quit()))
        btn = self.sender()
        anchor = btn.mapToGlobal(btn.rect().bottomLeft()) if btn is not None \
            else self.mapToGlobal(QPoint(0, 0))
        menu.exec(anchor)

    # ── live state ────────────────────────────────────────────────
    def set_state(self, state: str) -> None:
        text, colour = _STATE_DISPLAY.get(state, (state, _DEFAULT_DOT))
        self._state_label.setText(text)
        self._dot.setStyleSheet(f"color: {colour}; font-size: 11px;")

    def update_brand(self, name: str, avatar_path: str | None) -> None:
        """Refresh the header to the current character (name + profile icon)."""
        self._name_label.setText(name)
        path = avatar_path or asset_path(_AVATAR_ASSET) or icon_path_for(TrayState.RUNNING)
        if path:
            self._avatar_label.setPixmap(_circular_pixmap(str(path), 40))

    def _arm_dismiss(self) -> None:
        self._can_dismiss = True

    def _install_click_filter(self) -> None:
        if self._click_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._click_filter_installed = True

    def _remove_click_filter(self) -> None:
        if not self._click_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._click_filter_installed = False

    def _event_global_pos(self, watched: object, event: object) -> QPoint | None:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "globalPos"):
            return event.globalPos()
        if isinstance(watched, QWidget) and hasattr(event, "position"):
            return watched.mapToGlobal(event.position().toPoint())
        return None

    def _event_is_inside_menu(self, watched: object, event: object) -> bool:
        pos = self._event_global_pos(watched, event)
        if pos is not None:
            return self.frameGeometry().contains(pos)
        return watched is self or (
            isinstance(watched, QWidget) and self.isAncestorOf(watched)
        )

    # ── positioning ───────────────────────────────────────────────
    def popup_under(self, anchor: "QRectF | object | None") -> None:
        """Centre the card under the menu-bar icon with the caret pointing at it
        (``anchor`` is the icon's screen QRect); clamp to the screen but keep the
        caret aimed at the icon. Falls back to the primary screen's top-right."""
        from PySide6.QtWidgets import QApplication

        self.adjustSize()
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None

        icon_cx = x = y = None
        if anchor is not None and not anchor.isEmpty():
            icon_cx = anchor.center().x()
            x = icon_cx - self.width() / 2
            y = anchor.bottom() - 2  # tuck the caret just under the icon
        if x is None:
            if geo is not None:
                x = geo.right() - self.width() - 8
                y = geo.top() + 4
            else:
                x, y = 100, 40
            icon_cx = x + self.width() / 2

        if geo is not None:  # keep on-screen…
            x = max(geo.left() + 6, min(x, geo.right() - self.width() - 6))
        self._caret_x = max(16, min(self.width() - 16, icon_cx - x))  # …caret still aims
        self.update()
        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()
        self._install_click_filter()
        # Don't let the open sequence's own deactivation close us (happens when
        # another window — the TUI — was focused). Arm click-away after a beat.
        self._can_dismiss = False
        QTimer.singleShot(300, self._arm_dismiss)

    def paintEvent(self, event: object) -> None:  # noqa: N802 — Qt override
        """Draw the caret pointing up at the tray icon (card is a child frame)."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, apex_y, base_y, half = int(self._caret_x), 5, 15, 9
        tri = QPolygon([QPoint(cx - half, base_y), QPoint(cx + half, base_y),
                        QPoint(cx, apex_y)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPolygon(tri)
        p.setPen(QColor("#E5E7EB"))
        p.drawLine(cx - half, base_y, cx, apex_y)
        p.drawLine(cx + half, base_y, cx, apex_y)
        p.end()

    def focusOutEvent(self, event: object) -> None:  # noqa: N802 — Qt override
        if self._can_dismiss:
            self.hide()
        super().focusOutEvent(event)

    def event(self, e: object) -> bool:  # noqa: N802 — Qt override
        # A frameless Tool popup often never gets keyboard focus on macOS, so
        # focusOutEvent alone won't fire on click-away. WindowDeactivate fires
        # whenever the popup loses activation (click anywhere else) → close —
        # but only once armed, so opening over the TUI doesn't self-close.
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Type.WindowDeactivate and self._can_dismiss:
            self.hide()
        return super().event(e)

    def eventFilter(self, watched: object, event: object) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent
        if (self.isVisible()
                and self._can_dismiss
                and event.type() in {
                    QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonDblClick,
                    QEvent.Type.TouchBegin,
                }
                and not self._event_is_inside_menu(watched, event)):
            self.hide()
        return super().eventFilter(watched, event)

    def hideEvent(self, event: object) -> None:  # noqa: N802 — Qt override
        self._remove_click_filter()
        super().hideEvent(event)

    def closeEvent(self, event: object) -> None:  # noqa: N802 — Qt override
        self._remove_click_filter()
        super().closeEvent(event)


_STYLE = """
    QFrame#MenuCard {
        background-color: #FFFFFF;
        border-radius: 14px;
        border: 1px solid #E5E7EB;
    }
    QLabel#Name { font-size: 14px; font-weight: 600; color: #1F2937; }
    QLabel#Sub  { font-size: 11px; color: #8E8E93; }
    QFrame#StatusCard, QFrame#ActionCard {
        background-color: #F7F7F8;
        border: 1px solid #ECECEE;
        border-radius: 10px;
    }
    QLabel#StatusIcon { font-size: 18px; color: #007AFF; }
    QLabel#StatusTitle { font-size: 13px; font-weight: 600; color: #1F2937; }
    QLabel#StatusState { font-size: 12px; color: #6B7280; }
    QLabel#Chevron { font-size: 18px; color: #C7C7CC; }
    QPushButton#GearBtn {
        border: none; background: transparent;
        font-size: 17px; color: #8E8E93; padding: 2px 4px;
    }
    QPushButton#GearBtn:hover { color: #1F2937; }
    QPushButton#IconBtn {
        border: none; background: transparent;
        padding: 4px; border-radius: 7px;
    }
    QPushButton#IconBtn:hover { background-color: #F0F0F2; }
    QPushButton#ActionRow, QPushButton#DangerRow {
        text-align: left;
        border: none;
        border-radius: 8px;
        padding: 8px 10px;
        font-size: 13px;
        color: #1F2937;
        background: transparent;
    }
    QPushButton#ActionRow:hover { background-color: #F0F0F2; }
    QPushButton#DangerRow { color: #FF3B30; }
    QPushButton#DangerRow:hover { background-color: #FFF0F0; }
"""
