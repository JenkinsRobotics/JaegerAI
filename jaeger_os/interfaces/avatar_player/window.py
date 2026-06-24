"""Avatar player widgets: :class:`AvatarView` (embeddable — drops into the
Character Chat tab) + :class:`FloatingAvatarPlayer` (frameless popup).

Mirrors the media player: the media node streams ``/sense/media_frame`` to the
media popup; the animation/avatar node streams ``/sense/avatar_frame`` here.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AvatarView(QWidget):
    """Chrome-less surface that shows streamed avatar frames.

    Embeddable (the Character Chat tab drops it inline) and reused inside the
    floating popup. Frames arrive as RGBA8 bytes via :meth:`feed_frame`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("AvatarView")
        self._last: QPixmap | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("waiting for the avatar…")
        self._label.setObjectName("AvatarLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(220, 220)
        lay.addWidget(self._label)

    def feed_frame(self, data: bytes, w: int, h: int) -> None:
        """Render one RGBA frame streamed from the avatar node."""
        img = QImage(bytes(data), w, h, w * 4, QImage.Format.Format_RGBA8888)
        self._last = QPixmap.fromImage(img)
        self._rescale()

    def show_pixmap(self, pm: QPixmap) -> None:
        """Show a pixmap directly (e.g. a static card preview without the bus)."""
        if pm is not None and not pm.isNull():
            self._last = pm
            self._rescale()

    def _rescale(self) -> None:
        if self._last is not None and not self._last.isNull():
            self._label.setPixmap(self._last.scaled(
                self._label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e: Any) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(e)
        self._rescale()


class FloatingAvatarPlayer(QWidget):
    """Frameless, draggable, always-on-top avatar window (media-popup style)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Jaeger Avatar")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(340, 440)
        self.setStyleSheet(
            "QWidget{background:#0B0910;border-radius:16px;}"
            "QLabel#AvatarLabel{color:#8A85A6;font-size:13px;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.view = AvatarView()
        lay.addWidget(self.view)
        self._drag: Any = None

    def show_player(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    # ── drag + dismiss ────────────────────────────────────────────
    def mousePressEvent(self, e: Any) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: Any) -> None:  # noqa: N802
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e: Any) -> None:  # noqa: N802
        self._drag = None

    def keyPressEvent(self, e: Any) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.hide()


def make_surface(ctx: Any, spec: Any = None) -> FloatingAvatarPlayer:  # noqa: ARG001
    """Chassis surface — the only bus coupling. Subscribes to the avatar node's
    frame stream and shows whatever it renders. No core changes."""
    win = FloatingAvatarPlayer()
    bus = getattr(ctx, "bus", None)
    if bus is not None:
        from jaeger_os.app.surfaces import make_bus_bridge
        from jaeger_os.transport import topics
        win._bridge = make_bus_bridge(bus, [topics.SENSE_AVATAR_FRAME])

        def _on_msg(msg: Any) -> None:
            if getattr(msg, "topic", "") == topics.SENSE_AVATAR_FRAME:
                win.view.feed_frame(msg.data, msg.width, msg.height)
                if not win.isVisible():
                    win.show(); win.raise_()
        win._bridge.message.connect(_on_msg)
    return win
