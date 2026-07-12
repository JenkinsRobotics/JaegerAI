"""Companion surface: avatar (left) + live chat (right), framed to match the
Chat window.

A core JROS surface composed from :class:`AvatarView` + :class:`ChatWindow` — no
Studio dependency (Studio is splitting into its own app). Without a bus the chat
pane degrades to a placeholder, so the window still opens in the dev launcher.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from jaeger_ai.interfaces.avatar_player.animation import make_avatar
from jaeger_ai.interfaces.avatar_player.window import agent_name

_ICONS = {
    "mic": ('<rect x="9" y="2" width="6" height="12" rx="3"/>'
            '<path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>'),
    "mic_off": ('<rect x="9" y="2" width="6" height="12" rx="3"/>'
                '<path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/><path d="M3 3l18 18"/>'),
    "speaker": ('<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>'
                '<path d="M18.5 6a9 9 0 0 1 0 12"/>'),
    "speaker_off": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M16 9l6 6M22 9l-6 6"/>',
}


def _icon(name: str, color: str) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
           f'stroke-linejoin="round">{_ICONS[name]}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(20, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, 20, 20))
    p.end()
    return QIcon(pm)


class AvatarChatWindow(QWidget):
    """Avatar stage on the left, the live rich-TUI chat on the right."""

    def __init__(self, ctx: Any = None) -> None:
        super().__init__()
        self.ctx = ctx
        from jaeger_ai.interfaces.pyside6.rich_tui.window import (
            _CANVAS, _INK_DIM, _MONO, _PANEL, _RULE,
        )
        name = agent_name(ctx)
        self.setObjectName("JrosAvatarChatWindow")
        self.setWindowTitle(f"JROS — {name} · avatar + chat")
        self.resize(1240, 700)
        self.setStyleSheet(
            f"QWidget#JrosAvatarChatWindow {{ background-color: {_CANVAS}; }}"
            f"QFrame#Stage {{ background: {_PANEL}; border: 1px solid {_RULE};"
            f" border-radius: 12px; }}"
            f"QLabel#StageHeader {{ font-family: {_MONO[0]}, {_MONO[1]}, monospace;"
            f" font-size: 10px; color: {_INK_DIM}; }}"
            f"QLabel#AvatarLabel {{ color: {_INK_DIM}; font-size: 13px; }}")

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 14, 14, 14)
        h.setSpacing(12)

        stage = QFrame()
        stage.setObjectName("Stage")
        sv = QVBoxLayout(stage)
        sv.setContentsMargins(14, 12, 14, 14)
        sv.setSpacing(8)
        hdr = QLabel("AVATAR")
        hdr.setObjectName("StageHeader")
        sv.addWidget(hdr)
        self.view = make_avatar(ctx)   # active avatar-animation plugin (orb today)
        sv.addWidget(self.view, 1)
        sv.addLayout(self._controls(ctx))   # mic + speaker toggles
        h.addWidget(stage, 4)

        self.chat = self._build_chat(ctx)
        self.chat.setMinimumWidth(700)  # fit the 71-char JAEGER·OS banner unwrapped
        h.addWidget(self.chat, 5)

        # Speaker path: publish each final reply to the TTS node when on.
        self._speech_bridge = None
        bus = getattr(ctx, "bus", None)
        if bus is not None:
            try:
                from jaeger_os.app.surfaces import make_bus_bridge
                self._speech_bridge = make_bus_bridge(bus, ["/sense/chat"])
                self._speech_bridge.message.connect(self._maybe_speak)
            except Exception:  # noqa: BLE001
                self._speech_bridge = None

    # ── mic / speaker controls ──
    def _controls(self, ctx: Any) -> QHBoxLayout:
        mic_on, speaker_on = self._voice_defaults(ctx)
        self._mic_on = mic_on            # chat-mode default: mic OFF
        self._speaker_on = speaker_on    # default: speaker ON
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self._mic_btn = QPushButton()
        self._mic_btn.setObjectName("Ctl")
        self._mic_btn.setCheckable(True)
        self._mic_btn.setChecked(mic_on)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.setIconSize(QSize(20, 20))
        self._mic_btn.clicked.connect(self._toggle_mic)
        self._speaker_btn = QPushButton()
        self._speaker_btn.setObjectName("Ctl")
        self._speaker_btn.setCheckable(True)
        self._speaker_btn.setChecked(speaker_on)
        self._speaker_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._speaker_btn.setIconSize(QSize(20, 20))
        self._speaker_btn.clicked.connect(self._toggle_speaker)
        row.addWidget(self._mic_btn)
        row.addWidget(self._speaker_btn)
        row.addStretch(1)
        self._refresh_ctl_icons()
        self.setStyleSheet(self.styleSheet()
                           + "QPushButton#Ctl { background: rgba(255,255,255,0.05);"
                           " border: none; border-radius: 18px; padding: 8px; }"
                           " QPushButton#Ctl:checked { background: rgba(67,224,138,0.18); }")
        return row

    def _voice_defaults(self, ctx: Any) -> tuple[bool, bool]:
        try:
            from jaeger_ai.core.instance.instance import (
                InstanceLayout, resolve_instance_dir,
            )
            from jaeger_ai.core.instance.schemas import Config, load_yaml
            lay = getattr(ctx, "layout", None) or InstanceLayout(root=resolve_instance_dir())
            cfg = load_yaml(lay.config_path, Config)
            return bool(cfg.voice.enabled), bool(cfg.voice.speak_replies)
        except Exception:  # noqa: BLE001
            return False, True

    def _refresh_ctl_icons(self) -> None:
        acc, dim = "#43E08A", "#7C8A81"
        self._mic_btn.setIcon(_icon("mic" if self._mic_on else "mic_off",
                                    acc if self._mic_on else dim))
        self._mic_btn.setToolTip("Mic ON — voice input (applies on restart)"
                                 if self._mic_on else "Mic OFF — click to enable voice input")
        self._speaker_btn.setIcon(_icon("speaker" if self._speaker_on else "speaker_off",
                                        acc if self._speaker_on else dim))
        self._speaker_btn.setToolTip("Speaker ON — reads replies aloud"
                                     if self._speaker_on else "Speaker OFF")

    def _toggle_speaker(self) -> None:
        self._speaker_on = self._speaker_btn.isChecked()
        self._refresh_ctl_icons()

    def _toggle_mic(self) -> None:
        # No runtime mic-enable topic yet → persist voice.enabled (takes effect
        # on restart). Honest: the live mic can't flip mid-session today.
        self._mic_on = self._mic_btn.isChecked()
        self._refresh_ctl_icons()
        try:
            from jaeger_ai.core.instance.instance import (
                InstanceLayout, resolve_instance_dir,
            )
            from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
            lay = getattr(self.ctx, "layout", None) or InstanceLayout(root=resolve_instance_dir())
            cfg = load_yaml(lay.config_path, Config)
            cfg.voice.enabled = self._mic_on
            dump_yaml(lay.config_path, Config.model_validate(cfg.model_dump()))
        except Exception:  # noqa: BLE001
            pass

    def _maybe_speak(self, msg: Any) -> None:
        if not getattr(self, "_speaker_on", False):
            return
        text = getattr(msg, "text", "")
        if not text or getattr(msg, "topic", "") != "/sense/chat":
            return
        try:
            from jaeger_os.transport.topics import SpeechCommand
            self.ctx.bus.publish(SpeechCommand(text=text))
        except Exception:  # noqa: BLE001
            pass

    def _build_chat(self, ctx: Any) -> QWidget:
        if getattr(ctx, "bus", None) is not None:
            try:
                from jaeger_ai.interfaces.pyside6.rich_tui.window import ChatWindow
                return ChatWindow(ctx)
            except Exception:  # noqa: BLE001 — never let chat wiring break the window
                pass
        ph = QLabel("Chat connects when the agent is running.\n"
                    "Launch Jaeger from the tray to talk.")
        ph.setObjectName("AvatarLabel")
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setWordWrap(True)
        return ph


def make_surface(ctx: Any, spec: Any = None) -> AvatarChatWindow:  # noqa: ARG001
    return AvatarChatWindow(ctx)
