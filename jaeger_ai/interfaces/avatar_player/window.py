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

# The avatar node streams frames here (animation_dev/node.py). A literal string,
# not topics.SENSE_AVATAR_FRAME — that constant doesn't exist yet, and subscribing
# to an unpublished topic is a harmless no-op until the stream is wired.
_AVATAR_FRAME_TOPIC = "/sense/avatar_frame"


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
        try:
            win._bridge = make_bus_bridge(bus, [_AVATAR_FRAME_TOPIC])
        except Exception:  # noqa: BLE001 — bus may reject an unwired topic
            win._bridge = None
        if win._bridge is not None:
            def _on_msg(msg: Any) -> None:
                if getattr(msg, "topic", "") == _AVATAR_FRAME_TOPIC:
                    win.view.feed_frame(msg.data, msg.width, msg.height)
                    if not win.isVisible():
                        win.show(); win.raise_()
            win._bridge.message.connect(_on_msg)
    return win


# ── framed standalone avatar window (Chat-window chrome) ───────────────

def agent_name(ctx: Any) -> str:
    """Display name = the agent's NAME from identity.yaml (the unique instance
    the operator named), NEVER the active character. A character is only the
    persona being played — its name is a secondary reference, not the agent's
    identity ("name your robot Ted, it plays HAL" — operator 2026-07-05; see
    ``assemble._identity_name``). Falls back to the active character's name
    only if identity has none, then the core/instance name, then a default."""
    name = _identity_display_name(ctx)
    if name:
        return name
    c = resolve_character(ctx)
    if c is not None:
        return c.name
    return (getattr(getattr(ctx, "core", None), "agent_name", None)
            or getattr(ctx, "agent_name", None) or "agent")


def _identity_display_name(ctx: Any) -> str:
    """``identity.yaml`` ``name`` for the ctx's instance (its layout, else the
    process's current instance dir). Empty string if unavailable/unset."""
    try:
        from jaeger_ai.core.instance.instance import (
            InstanceLayout, resolve_instance_dir,
        )
        from jaeger_ai.core.instance.schemas import Identity, load_yaml
        id_path = getattr(getattr(ctx, "layout", None), "identity_path", None)
        if id_path is None:
            id_path = InstanceLayout(root=resolve_instance_dir()).identity_path
        return (load_yaml(id_path, Identity).name or "").strip()
    except Exception:  # noqa: BLE001 — a broken identity never breaks a title
        return ""


def resolve_character(ctx: Any) -> Any:
    """The character to display — the instance's active one, else the library
    default, else None. Lets a surface show a real card even standalone."""
    try:
        from jaeger_ai.personality.character import (
            DEFAULT_CHARACTER_ID, active_character, list_characters,
        )
        root = getattr(getattr(ctx, "layout", None), "root", None)
        if root is None:
            # No layout on ctx → use the process's current instance dir, so we
            # still resolve the ACTIVE character (not the jarvis default).
            try:
                from jaeger_ai.core.instance.instance import resolve_instance_dir
                root = resolve_instance_dir()
            except Exception:  # noqa: BLE001
                root = None
        if root is not None:
            c = active_character(root)
            if c is not None:
                return c
        chars = list_characters()
        for c in chars:
            if c.id == DEFAULT_CHARACTER_ID:
                return c
        return chars[0] if chars else None
    except Exception:  # noqa: BLE001
        return None


def show_card(view: "AvatarView", character: Any) -> None:
    """Show a character's card image on a view (static fallback before frames)."""
    from PySide6.QtGui import QPixmap
    if character is not None and character.card_path():
        view.show_pixmap(QPixmap(str(character.card_path())))


def wire_avatar_frames(view: "AvatarView", ctx: Any) -> Any:
    """Subscribe a view to the avatar node's frame stream. Returns the bridge
    (hold a ref to keep it alive) or None when there's no bus."""
    bus = getattr(ctx, "bus", None)
    if bus is None:
        return None
    from jaeger_os.app.surfaces import make_bus_bridge
    try:
        bridge = make_bus_bridge(bus, [_AVATAR_FRAME_TOPIC])
    except Exception:  # noqa: BLE001 — bus may reject an unwired topic
        return None

    def _on(msg: Any) -> None:
        if getattr(msg, "topic", "") == _AVATAR_FRAME_TOPIC:
            view.feed_frame(msg.data, msg.width, msg.height)

    bridge.message.connect(_on)
    return bridge


class AvatarWindow(QWidget):
    """Framed standalone avatar window — same chrome as the Chat window, avatar
    only. (The frameless overlay above is a separate surface.)"""

    def __init__(self, ctx: Any = None) -> None:
        super().__init__()
        self.ctx = ctx
        from jaeger_ai.interfaces.pyside6.rich_tui.window import (
            _CANVAS, _INK_DIM, _MONO, _PANEL, _RULE,
        )
        name = agent_name(ctx)
        self.setObjectName("JrosAvatarWindow")
        self.setWindowTitle(f"JROS — {name} · avatar")
        self.resize(420, 560)
        self.setStyleSheet(
            f"QWidget#JrosAvatarWindow {{ background-color: {_CANVAS}; }}"
            f"QLabel#AvatarHeader {{ font-family: {_MONO[0]}, {_MONO[1]}, monospace;"
            f" font-size: 12px; color: {_INK_DIM}; padding: 8px 16px;"
            f" background: {_PANEL}; border-bottom: 1px solid {_RULE}; }}"
            f"QLabel#AvatarLabel {{ color: {_INK_DIM}; font-size: 13px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        header = QLabel(f"jros · {name} · avatar")
        header.setObjectName("AvatarHeader")
        v.addWidget(header)
        from jaeger_ai.interfaces.avatar_player.animation import make_avatar
        self.view = make_avatar(ctx)   # active avatar-animation plugin (orb today)
        v.addWidget(self.view, 1)


def make_window_surface(ctx: Any, spec: Any = None) -> AvatarWindow:  # noqa: ARG001
    """Chassis surface — the framed avatar window, wired to the avatar stream."""
    return AvatarWindow(ctx)
