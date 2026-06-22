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

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
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

    def __init__(self, *, agent_name: str, instance_name: str,
                 on_quick_input: Callable[[], None],
                 on_open_chat: Callable[[], None],
                 on_quit: Callable[[], None],
                 on_settings: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_open_chat = on_open_chat
        self._on_settings = on_settings

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(320)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

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

        body.addLayout(self._header(agent_name, instance_name))
        body.addWidget(self._status_card())
        body.addWidget(self._action("Quick input…", on_quick_input))
        body.addWidget(self._action("Open chat window", on_open_chat))
        body.addWidget(self._action("Quit JROS", on_quit, danger=True))

        outer.addWidget(card)
        self.set_state("idle")

    # ── sections ──────────────────────────────────────────────────
    def _header(self, agent_name: str, instance_name: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        avatar = QLabel()
        avatar.setObjectName("Avatar")
        avatar.setFixedSize(40, 40)
        avatar_path = asset_path(_AVATAR_ASSET) or icon_path_for(TrayState.RUNNING)
        if avatar_path:
            avatar.setPixmap(_circular_pixmap(avatar_path, 40))
        row.addWidget(avatar)

        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(agent_name)
        name.setObjectName("Name")
        sub = QLabel(instance_name)
        sub.setObjectName("Sub")
        text.addWidget(name)
        text.addWidget(sub)
        row.addLayout(text)
        row.addStretch()

        gear = QPushButton("⚙")
        gear.setObjectName("GearBtn")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setFlat(True)
        gear.setToolTip("Settings")
        gear.clicked.connect(self._open_settings)
        row.addWidget(gear)
        return row

    def _open_settings(self) -> None:
        self.hide()
        if self._on_settings is not None:
            self._on_settings()

    def _status_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("StatusCard")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        icon = QLabel("◴")
        icon.setObjectName("StatusIcon")
        lay.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel("Agent Status")
        title.setObjectName("StatusTitle")
        # dot + text on one line — set live by set_state().
        line = QHBoxLayout()
        line.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setObjectName("StatusDot")
        self._state_label = QLabel("Standing by")
        self._state_label.setObjectName("StatusState")
        line.addWidget(self._dot)
        line.addWidget(self._state_label)
        line.addStretch()
        col.addWidget(title)
        col.addLayout(line)
        lay.addLayout(col)
        lay.addStretch()

        chevron = QLabel("›")
        chevron.setObjectName("Chevron")
        lay.addWidget(chevron)
        return frame

    def _action(self, label: str, slot: Callable[[], None],
                danger: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName("DangerRow" if danger else "ActionRow")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: (self.hide(), slot()))
        return btn

    # ── live state ────────────────────────────────────────────────
    def set_state(self, state: str) -> None:
        text, colour = _STATE_DISPLAY.get(state, (state, _DEFAULT_DOT))
        self._state_label.setText(text)
        self._dot.setStyleSheet(f"color: {colour}; font-size: 11px;")

    # ── positioning ───────────────────────────────────────────────
    def popup_under(self, anchor: "QRectF | object | None") -> None:
        """Show top-right-aligned under the menu-bar icon (``anchor`` is the
        icon's screen QRect); fall back to the primary screen's top-right."""
        from PySide6.QtWidgets import QApplication

        self.adjustSize()
        x = y = None
        if anchor is not None and not anchor.isEmpty():
            x = anchor.right() - self.width() + 12
            y = anchor.bottom()
        if x is None:
            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else None
            if geo is not None:
                x = geo.right() - self.width() - 8
                y = geo.top() + 4
            else:
                x, y = 100, 40
        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()

    def focusOutEvent(self, event: object) -> None:  # noqa: N802 — Qt override
        self.hide()
        super().focusOutEvent(event)


_STYLE = """
    QFrame#MenuCard {
        background-color: #FFFFFF;
        border-radius: 14px;
        border: 1px solid #E5E7EB;
    }
    QLabel#Name { font-size: 14px; font-weight: 600; color: #1F2937; }
    QLabel#Sub  { font-size: 11px; color: #8E8E93; }
    QFrame#StatusCard {
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
