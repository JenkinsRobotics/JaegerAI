"""Pill — a floating Claude-style quick-input launcher.

A tray-spawned window (not a boot-time ``[[surface]]``): the tray shows it
on click, the user types one line, and submitting hands the text to the
tray's ``on_submit`` callback — which opens the chat window and renders it
there. The Pill itself is pure UI: no bus, no agent.

Two-row card, 1:1 with the Lilith ``PillWindow`` (and Claude's quick-input
widget): an input row (glyph + field + "New Chat ▾" + send) over a callout
row (a share-content blurb + placeholder action chips). The bottom-row
chips are intentional affordances — "Turn on screenshots" is a labelled
placeholder ("coming soon"), "Not now" dismisses.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class Pill(QWidget):
    """Frameless, stay-on-top quick-input card. Dismisses on focus loss."""

    def __init__(self, on_submit: Callable[[str], None],
                 agent_name: str = "agent",
                 on_open_chat: Callable[[], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self._on_open_chat = on_open_chat
        self._agent_name = agent_name

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(720, 140)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        card = QFrame()
        card.setObjectName("PillCard")
        card.setStyleSheet("""
            QFrame#PillCard {
                background-color: #F7F7F8;
                border-radius: 16px;
                border: 1px solid #E5E7EB;
            }
            QLabel#PillGlyph { font-size: 22px; background: transparent; }
            QLineEdit#PillInput {
                background: transparent;
                border: none;
                font-size: 16px;
                color: #222222;
            }
            QPushButton#PillNewChat {
                background: transparent;
                border: none;
                color: #666666;
                font-size: 14px;
                padding: 4px 8px;
            }
            QPushButton#PillNewChat:hover { color: #222222; }
            QPushButton#PillNewChat::menu-indicator { image: none; }
            QPushButton#PillSend {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton#PillSend:hover { background-color: #0A84FF; }
            QPushButton#PillSend:disabled { background-color: #B2D9FF; }
            QLabel#PillTitle {
                font-weight: bold; font-size: 13px; color: #222222;
            }
            QLabel#PillSubtitle { font-size: 11px; color: #888888; }
            QPushButton#PillChip {
                background-color: #EBEBEB;
                color: #222222;
                border: 1px solid #DFDFDF;
                border-radius: 12px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton#PillChip:hover { background-color: #D1D1D1; }
            QFrame#PillDivider { background-color: #E5E7EB; border: none; }
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 30))
        shadow.setOffset(0, 8)
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(10)

        # ── Top row: glyph + input + "New Chat ▾" + send ──────────────
        top = QHBoxLayout()
        top.setSpacing(12)

        glyph = QLabel()
        glyph.setObjectName("PillGlyph")
        # The J brand mark (jaeger_icon.png), scaled into the row. Falls
        # back to a sparkler glyph if the assets dir is stripped.
        from jaeger_os.interfaces.pyside6.tray.base import (
            TrayState, icon_path_for,
        )
        j_path = icon_path_for(TrayState.RUNNING)
        if j_path:
            glyph.setPixmap(QPixmap(j_path).scaled(
                24, 24,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            glyph.setText("🎇")
        top.addWidget(glyph)

        self.input = QLineEdit()
        self.input.setObjectName("PillInput")
        self.input.setPlaceholderText("What can I help you with today?")
        self.input.returnPressed.connect(self._send)
        top.addWidget(self.input, stretch=1)

        new_chat = QPushButton("New Chat ▾")
        new_chat.setObjectName("PillNewChat")
        new_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        chat_menu = QMenu(self)
        chat_menu.addAction("Open Chat Window", self._open_chat)
        new_chat.setMenu(chat_menu)
        top.addWidget(new_chat)

        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("PillSend")
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._send)
        top.addWidget(self.send_btn)
        card_layout.addLayout(top)

        # ── Divider ───────────────────────────────────────────────────
        divider = QFrame()
        divider.setObjectName("PillDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        card_layout.addWidget(divider)

        # ── Bottom row: share-content blurb + action chips ────────────
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(10)

        text_block = QVBoxLayout()
        text_block.setSpacing(2)
        title = QLabel(f"Quickly share content with {self._agent_name}")
        title.setObjectName("PillTitle")
        subtitle = QLabel("Needs additional permission")
        subtitle.setObjectName("PillSubtitle")
        text_block.addWidget(title)
        text_block.addWidget(subtitle)
        bottom.addLayout(text_block)
        bottom.addStretch()

        # Placeholder — a labelled affordance, wired to a harmless toast.
        # When a vision skill lands this routes to its bus topic.
        screenshots = QPushButton("Turn on screenshots")
        screenshots.setObjectName("PillChip")
        screenshots.setCursor(Qt.CursorShape.PointingHandCursor)
        screenshots.setToolTip("Coming soon — will route to the vision skill.")
        bottom.addWidget(screenshots)

        dismiss = QPushButton("Not now")
        dismiss.setObjectName("PillChip")
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.clicked.connect(self.hide)
        bottom.addWidget(dismiss)

        card_layout.addLayout(bottom)
        outer.addWidget(card)

    # ── behavior ──────────────────────────────────────────────────
    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.hide()
        self._on_submit(text)   # tray opens the chat window + renders it there

    def _open_chat(self) -> None:
        """"New Chat ▾" → Open Chat Window. Dismiss the pill first."""
        self.hide()
        if self._on_open_chat is not None:
            self._on_open_chat()

    def popup(self) -> None:
        """Center near the bottom of the primary screen, show, and focus."""
        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.bottom() - self.height() - 100)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def event(self, e: Any) -> bool:  # noqa: N802 — Qt override
        # A quick-launcher dismisses when you click away. We watch the
        # WINDOW deactivating (not ``focusOutEvent`` — the input child
        # holds focus, so the top-level widget never sees a focus-out, so
        # the pill used to stay open). Guard against our own ``New Chat ▾``
        # dropdown: while that popup is up, the pill deactivates but
        # shouldn't close.
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        if (e.type() == QEvent.Type.WindowDeactivate
                and QApplication.activePopupWidget() is None):
            self.hide()
        return super().event(e)
