"""VoiceOrb — the agent's face inside a reactive voice-spectrum ring.

The only avatar animation JROS ships for now. Two live states off the bus:

  * thinking  (/sense/agent_state state="thinking") → a travelling wave-gradient
    shimmers around the ring.
  * speaking  (/sense/tts_chunk amplitude 0..1, ~30 Hz while the voice plays) →
    the ring's radial bars react to the real output amplitude.

Idle otherwise: a slow breathing ring. Colours run cyan (left) → purple → pink
(right), matching the reference orb. Self-wires to the bus from ``ctx``.
"""
from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

_BARS = 72
_AGENT_STATE = "/sense/agent_state"
_TTS_CHUNK = "/sense/tts_chunk"      # amplitude proxy (fallback)
_AUDIO_OUT = "/act/audio_out"        # real float32 PCM → true FFT spectrum


class VoiceOrb(QWidget):
    def __init__(self, ctx: Any = None) -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("VoiceOrb")
        self.setMinimumSize(240, 240)
        self._vals = [0.0] * _BARS
        self._phase = 0.0
        self._state = "idle"        # raw /sense/agent_state
        self._level = 0.0           # last TTS amplitude (proxy)
        self._speak_frames = 0      # frames left to keep 'speaking' after a chunk
        self._spectrum = [0.0] * _BARS   # last real FFT spectrum (per bar)
        self._spec_frames = 0       # frames left to use the real spectrum
        self._face: QPixmap | None = None

        self._load_face()
        self._wire_bus()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)       # ~30 fps

    # ── data ──
    def _load_face(self) -> None:
        try:
            from jaeger_os.interfaces.avatar_player.window import resolve_character
            c = resolve_character(self.ctx)
            if c is not None and c.card_path():
                self._face = QPixmap(str(c.card_path()))
        except Exception:  # noqa: BLE001
            self._face = None

    def _wire_bus(self) -> None:
        self._bridge = None
        bus = getattr(self.ctx, "bus", None)
        if bus is None:
            return
        from jaeger_os.app.surfaces import make_bus_bridge
        try:
            self._bridge = make_bus_bridge(bus, [_AGENT_STATE, _TTS_CHUNK, _AUDIO_OUT])
            self._bridge.message.connect(self._on_msg)
        except Exception:  # noqa: BLE001
            self._bridge = None

    def _on_msg(self, msg: Any) -> None:
        topic = getattr(msg, "topic", "")
        if topic == _AGENT_STATE:
            self._state = getattr(msg, "state", "") or "idle"
        elif topic == _TTS_CHUNK:
            self._level = max(0.0, min(1.0, float(getattr(msg, "amplitude", 0.0))))
            self._speak_frames = 9   # ~0.3 s of speaking after the last chunk
        elif topic == _AUDIO_OUT:
            self._on_audio(msg)

    def _on_audio(self, msg: Any) -> None:
        """Real spectrum from the output PCM — FFT → per-bar magnitudes."""
        try:
            import numpy as np
            raw = getattr(msg, "samples", b"")
            if not raw:
                return
            x = np.frombuffer(raw, dtype="<f4")
            if x.size < 32:
                return
            n = min(2048, x.size)
            seg = x[:n].astype(np.float32) * np.hanning(n).astype(np.float32)
            mag = np.abs(np.fft.rfft(seg))
            usable = mag[: max(2, len(mag) // 2)]   # voice energy lives low
            spec = np.array([b.mean() if b.size else 0.0
                             for b in np.array_split(usable, _BARS)], dtype=np.float32)
            peak = float(spec.max())
            if peak > 1e-6:
                spec = np.sqrt(spec / peak)          # compress so quiet detail shows
            self._spectrum = spec.tolist()
            self._spec_frames = 5                    # ~0.15 s per audio frame
        except Exception:  # noqa: BLE001 — any failure → proxy path stays live
            pass

    # ── animation ──
    def _tick(self) -> None:
        self._phase += 0.16
        have_spec = self._spec_frames > 0        # real FFT wins when fresh
        if self._spec_frames > 0:
            self._spec_frames -= 1
        speaking = self._speak_frames > 0        # amplitude proxy fallback
        if self._speak_frames > 0:
            self._speak_frames -= 1
        for i in range(_BARS):
            a = i / _BARS
            if have_spec:
                target = 0.06 + 0.92 * self._spectrum[i]
            elif speaking:
                env = 0.30 + 0.70 * abs(math.sin(a * math.tau * 5 + self._phase * 1.4))
                target = self._level * env
            elif self._state == "thinking":
                target = 0.20 + 0.16 * (0.5 + 0.5 * math.sin(a * math.tau * 3 + self._phase))
            else:  # idle breathing
                target = 0.09 + 0.05 * (0.5 + 0.5 * math.sin(a * math.tau * 2 + self._phase * 0.4))
            self._vals[i] += (target - self._vals[i]) * 0.4
        self.update()

    # ── paint ──
    def paintEvent(self, e: Any) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.22          # face-circle radius
        bar_max = min(w, h) * 0.16

        # backdrop glow
        glow = QRadialGradient(cx, cy, r * 2.6)
        glow.setColorAt(0.0, QColor(90, 120, 255, 60))
        glow.setColorAt(1.0, QColor(10, 14, 22, 0))
        p.fillRect(self.rect(), glow)

        # radial spectrum
        for i in range(_BARS):
            ang = (i / _BARS) * math.tau
            val = self._vals[i]
            r0 = r + 8
            r1 = r0 + val * bar_max
            hue = int(190 + 135 * (0.5 + 0.5 * math.cos(ang)))   # left cyan → right pink
            alpha = 90 + int(150 * min(1.0, val * 2.2))
            p.setPen(QPen(QColor.fromHsv(hue % 360, 210, 255, alpha), 2.4,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(int(cx + math.cos(ang) * r0), int(cy + math.sin(ang) * r0),
                       int(cx + math.cos(ang) * r1), int(cy + math.sin(ang) * r1))

        # face circle
        rf = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        if self._face is not None and not self._face.isNull():
            p.save()
            clip = QPainterPath()
            clip.addEllipse(rf)
            p.setClipPath(clip)
            sc = self._face.scaled(int(2 * r), int(2 * r),
                                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(cx - sc.width() / 2), int(cy - sc.height() / 2), sc)
            p.restore()
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(12, 16, 24))
            p.drawEllipse(rf)
            self._draw_mic(p, cx, cy, r)
        # ring outline
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(120, 150, 255, 120), 1.5))
        p.drawEllipse(rf)
        p.end()

    def _draw_mic(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        p.setPen(QPen(QColor(90, 220, 255), max(2.0, r * 0.06),
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cap = r * 0.34
        body = QRectF(cx - cap * 0.5, cy - r * 0.42, cap, cap * 1.5)
        p.drawRoundedRect(body, cap * 0.5, cap * 0.5)
        p.drawArc(QRectF(cx - cap * 0.85, cy - r * 0.28, cap * 1.7, cap * 1.6),
                  200 * 16, 140 * 16)
        p.drawLine(int(cx), int(cy + r * 0.28), int(cx), int(cy + r * 0.5))
