#!/usr/bin/env python3
"""Standalone Video & Voice Chat Test for JaegerAI.

Features:
  - Live 1080p camera feed (Insta360 Link 2 / default webcam via OpenCV)
  - Live Push-to-Talk microphone recording via sounddevice
  - Metal GPU-accelerated speech-to-text with Whisper
  - Direct connection to resident Jaeger agent (Iris / Gemma) via bridge.sock
  - Real-time text-to-speech voice playback with Kokoro TTS through speakers
  - Animated pulsing Voice Orb with live amplitude reaction
  - Camera snapshot / visual context trigger
"""

from __future__ import annotations

import collections
import json
import math
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import sounddevice as sd
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# ── Bridge Client ─────────────────────────────────────────────────────────────

def find_active_bridge_socket() -> Path | None:
    """Locate an active, responsive bridge.sock in ~/.jaeger."""
    instances_dir = Path.home() / ".jaeger" / "instances"
    for sock_path in instances_dir.glob("*/run/bridge.sock"):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect(str(sock_path))
            ready_raw = s.recv(4096)
            s.close()
            if b'"ready"' in ready_raw:
                return sock_path
        except Exception:
            continue
    return None


class BridgeTurnClient:
    def __init__(self, sock_path: Path):
        self.sock_path = sock_path

    def send_turn(self, text: str) -> str:
        """Send a turn to the bridge and collect the reply text."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30.0)
        s.connect(str(self.sock_path))
        # Drain ready frame
        _ = s.recv(4096)
        payload = json.dumps({"op": "turn", "text": text}) + "\n"
        s.sendall(payload.encode("utf-8"))

        reply_parts: list[str] = []
        buf = ""
        while True:
            chunk = s.recv(4096).decode("utf-8")
            if not chunk:
                break
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                msg_type = msg.get("type")
                if msg_type == "delta":
                    reply_parts.append(msg.get("text", ""))
                elif msg_type == "reply":
                    # If deltas were received, reply is full text
                    full_text = msg.get("text") or "".join(reply_parts)
                    s.close()
                    return full_text
                elif msg_type == "done":
                    s.close()
                    return "".join(reply_parts)
                elif msg_type == "fatal":
                    s.close()
                    return f"Agent error: {msg.get('error', 'unknown error')}"
        s.close()
        return "".join(reply_parts) or "I didn't receive a response."


# ── Camera Worker ─────────────────────────────────────────────────────────────

class CameraWorker(QThread):
    frame_ready = Signal(QImage)
    status_msg = Signal(str)

    def __init__(self, camera_index: int = 0):
        super().__init__()
        self.camera_index = camera_index
        self.running = True
        self.latest_frame: np.ndarray | None = None
        self._lock = threading.Lock()

    def run(self):
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            # Try fallback camera index 1 or 2
            for alt_idx in [1, 2, 0]:
                if alt_idx == self.camera_index:
                    continue
                cap = cv2.VideoCapture(alt_idx)
                if cap.isOpened():
                    self.camera_index = alt_idx
                    break

        if not cap.isOpened():
            self.status_msg.emit("Camera: Not Detected")
            return

        # Request 1080p
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.status_msg.emit(f"Camera: Online (Device {self.camera_index})")

        while self.running:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.03)
                continue

            with self._lock:
                self.latest_frame = frame.copy()

            # Convert BGR to RGB for Qt
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
            self.frame_ready.emit(q_img)
            time.sleep(0.033)  # ~30 FPS

        cap.release()

    def get_snapshot(self) -> np.ndarray | None:
        with self._lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
        return None

    def stop(self):
        self.running = False
        self.wait(1000)


# ── Voice Orb Widget ──────────────────────────────────────────────────────────

class VoiceOrbWidget(QWidget):
    """Futuristic glowing Voice Orb that responds to speech and audio amplitude."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.state = "idle"  # "idle", "listening", "thinking", "speaking"
        self.phase = 0.0
        self.amplitude = 0.0
        self.target_amplitude = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(25)  # 40 FPS

    def set_state(self, state: str):
        self.state = state
        self.update()

    def set_amplitude(self, amp: float):
        self.target_amplitude = min(1.0, max(0.0, amp))

    def _tick(self):
        self.phase += 0.06
        if self.phase > 2 * math.pi:
            self.phase -= 2 * math.pi
        # Smooth amplitude lerp
        self.amplitude += (self.target_amplitude - self.amplitude) * 0.25
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        center = QPointF(w / 2, h / 2)
        base_radius = min(w, h) * 0.32

        # State color styling
        if self.state == "listening":
            c_core = QColor(16, 185, 129)     # Emerald / Mint
            c_glow = QColor(5, 150, 105, 120)
            c_outer = QColor(16, 185, 129, 30)
            amp_boost = self.amplitude * 45.0
        elif self.state == "thinking":
            c_core = QColor(14, 165, 233)     # Cyan / Sky
            c_glow = QColor(2, 132, 199, 130)
            c_outer = QColor(56, 189, 248, 35)
            amp_boost = math.sin(self.phase * 3.0) * 12.0
        elif self.state == "speaking":
            c_core = QColor(245, 158, 11)     # Amber / Gold
            c_glow = QColor(217, 119, 6, 140)
            c_outer = QColor(251, 191, 36, 40)
            amp_boost = self.amplitude * 55.0
        else:  # idle
            c_core = QColor(99, 102, 241)     # Indigo / Violet
            c_glow = QColor(79, 70, 229, 90)
            c_outer = QColor(129, 140, 248, 20)
            amp_boost = math.sin(self.phase) * 6.0

        current_radius = base_radius + amp_boost

        # Outer ambient glow
        outer_grad = QRadialGradient(center, current_radius * 1.5)
        outer_grad.setColorAt(0.0, c_outer)
        outer_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(outer_grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, current_radius * 1.5, current_radius * 1.5)

        # Core glowing sphere
        core_grad = QRadialGradient(
            QPointF(center.x() - current_radius * 0.25, center.y() - current_radius * 0.25),
            current_radius,
        )
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 220))
        core_grad.setColorAt(0.4, c_core)
        core_grad.setColorAt(0.85, c_glow)
        core_grad.setColorAt(1.0, QColor(10, 15, 30, 240))

        painter.setBrush(QBrush(core_grad))
        painter.setPen(QPen(c_core, 1.5))
        painter.drawEllipse(center, current_radius, current_radius)

        # Harmonic waveform rings when listening or speaking
        if self.state in ("listening", "speaking") and self.amplitude > 0.05:
            painter.setBrush(Qt.NoBrush)
            for i in range(3):
                ring_r = current_radius + (i + 1) * (10.0 + self.amplitude * 20.0)
                alpha = int(max(0, 160 - (i * 50) - (self.amplitude * 40)))
                ring_color = QColor(c_core.red(), c_core.green(), c_core.blue(), alpha)
                painter.setPen(QPen(ring_color, 1.5, Qt.DashLine))
                painter.drawEllipse(center, ring_r, ring_r)


# ── Audio Recording & Processing ──────────────────────────────────────────────

class AudioRecorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.stream: sd.InputStream | None = None
        self.frames: list[np.ndarray] = []
        self.is_recording = False
        self.current_amplitude = 0.0

    def start(self):
        self.frames.clear()
        self.is_recording = True

        def callback(indata, frames, time_info, status):
            if not self.is_recording:
                return
            audio_copy = indata.copy().flatten()
            self.frames.append(audio_copy)
            # Compute RMS amplitude
            rms = np.sqrt(np.mean(audio_copy**2)) if len(audio_copy) > 0 else 0.0
            self.current_amplitude = float(rms)

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=callback,
                blocksize=1024,
            )
            self.stream.start()
        except Exception as e:
            print(f"[AudioRecorder] start error: {e}", file=sys.stderr)

    def stop(self) -> np.ndarray:
        self.is_recording = False
        self.current_amplitude = 0.0
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if not self.frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.frames)


# ── Main Video Chat Window ────────────────────────────────────────────────────

class StandaloneVideoChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JaegerAI — Standalone Video & Voice Chat Test")
        self.resize(1180, 720)
        self.setMinimumSize(960, 580)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d1117;
            }
            QWidget {
                color: #e6edf3;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            }
            QFrame.card {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 12px;
            }
            QLabel.title {
                font-size: 16px;
                font-weight: bold;
                color: #58a6ff;
            }
            QLabel.badge {
                font-size: 12px;
                font-weight: 600;
                padding: 4px 10px;
                border-radius: 6px;
                background-color: #21262d;
                border: 1px solid #30363d;
            }
            QPushButton.action {
                background-color: #238636;
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
            }
            QPushButton.action:hover {
                background-color: #2ea043;
            }
            QPushButton.action:pressed {
                background-color: #1a7f37;
            }
            QPushButton.action_rec {
                background-color: #da3633;
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
            }
            QPushButton.secondary {
                background-color: #21262d;
                color: #c9d1d9;
                font-size: 13px;
                font-weight: 500;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 8px 14px;
            }
            QPushButton.secondary:hover {
                background-color: #30363d;
                color: #ffffff;
            }
            QLineEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 14px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #58a6ff;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QProgressBar {
                background-color: #21262d;
                border-radius: 4px;
                border: none;
                text-align: center;
                height: 8px;
            }
            QProgressBar::chunk {
                background-color: #2ea043;
                border-radius: 4px;
            }
        """)

        # Backend components
        self.recorder = AudioRecorder(sample_rate=16000)
        self.whisper_model: Any = None
        self.kokoro_tts: Any = None
        self.bridge_path = find_active_bridge_socket()
        self.speaker_enabled = True

        # Build UI layout
        self._init_ui()

        # Start Camera Thread
        self.camera_worker = CameraWorker(camera_index=0)
        self.camera_worker.frame_ready.connect(self._on_frame_ready)
        self.camera_worker.status_msg.connect(self.cam_badge.setText)
        self.camera_worker.start()

        # Audio Metering Timer
        self.audio_timer = QTimer(self)
        self.audio_timer.timeout.connect(self._on_audio_tick)
        self.audio_timer.start(35)

        # Background Warm Models
        threading.Thread(target=self._warm_voice_stack, daemon=True).start()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # ── LEFT PANE: Video Feed & Camera Controls ───────────────────────────
        left_card = QFrame()
        left_card.setProperty("class", "card")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(12)

        # Header
        cam_header = QHBoxLayout()
        cam_title = QLabel("Video Feed")
        cam_title.setProperty("class", "title")
        self.cam_badge = QLabel("Camera: Connecting…")
        self.cam_badge.setProperty("class", "badge")
        cam_header.addWidget(cam_title)
        cam_header.addStretch()
        cam_header.addWidget(self.cam_badge)
        left_layout.addLayout(cam_header)

        # Video Frame Container
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_label.setStyleSheet("""
            background-color: #05070a;
            border: 1px solid #21262d;
            border-radius: 8px;
        """)
        self.video_label.setMinimumSize(480, 320)
        left_layout.addWidget(self.video_label)

        # Camera Controls
        cam_controls = QHBoxLayout()
        self.btn_snapshot = QPushButton("📸 Snapshot to AI")
        self.btn_snapshot.setProperty("class", "secondary")
        self.btn_snapshot.clicked.connect(self._on_snapshot_clicked)

        self.btn_switch_cam = QPushButton("🔄 Switch Camera")
        self.btn_switch_cam.setProperty("class", "secondary")
        self.btn_switch_cam.clicked.connect(self._on_switch_cam_clicked)

        cam_controls.addWidget(self.btn_snapshot)
        cam_controls.addWidget(self.btn_switch_cam)
        cam_controls.addStretch()
        left_layout.addLayout(cam_controls)

        main_layout.addWidget(left_card, 55)

        # ── RIGHT PANE: AI Avatar, Transcript & Voice Controls ────────────────
        right_card = QFrame()
        right_card.setProperty("class", "card")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(12)

        # Header
        agent_header = QHBoxLayout()
        agent_title = QLabel("AI Companion")
        agent_title.setProperty("class", "title")
        self.status_badge = QLabel(
            f"Agent: {'Online (Iris)' if self.bridge_path else 'Standalone'}"
        )
        self.status_badge.setProperty("class", "badge")
        agent_header.addWidget(agent_title)
        agent_header.addStretch()
        agent_header.addWidget(self.status_badge)
        right_layout.addLayout(agent_header)

        # Voice Orb Stage
        orb_container = QHBoxLayout()
        orb_container.addStretch()
        self.voice_orb = VoiceOrbWidget()
        orb_container.addWidget(self.voice_orb)
        orb_container.addStretch()
        right_layout.addLayout(orb_container)

        self.lbl_stage_status = QLabel("Ready · Hold Space or Push to Talk")
        self.lbl_stage_status.setAlignment(Qt.AlignCenter)
        self.lbl_stage_status.setStyleSheet("font-size: 13px; color: #8b949e; font-weight: 500;")
        right_layout.addWidget(self.lbl_stage_status)

        # Mic Level Bar
        self.mic_bar = QProgressBar()
        self.mic_bar.setRange(0, 100)
        self.mic_bar.setValue(0)
        self.mic_bar.setFixedHeight(6)
        right_layout.addWidget(self.mic_bar)

        # Transcript Scroll Area
        self.transcript_area = QTextEdit()
        self.transcript_area.setReadOnly(True)
        self.transcript_area.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                border: 1px solid #21262d;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                line-height: 1.4;
            }
        """)
        self._append_message("System", "Video & Voice chat initialized. Press 'Push to Talk' or hold Spacebar to speak!")
        right_layout.addWidget(self.transcript_area, 1)

        # Voice & Audio Buttons
        audio_btn_row = QHBoxLayout()
        self.btn_ptt = QPushButton("🎙 Push to Talk")
        self.btn_ptt.setProperty("class", "action")
        self.btn_ptt.clicked.connect(self._toggle_ptt)

        self.btn_speaker = QPushButton("🔊 Speaker: ON")
        self.btn_speaker.setProperty("class", "secondary")
        self.btn_speaker.clicked.connect(self._toggle_speaker)

        audio_btn_row.addWidget(self.btn_ptt, 2)
        audio_btn_row.addWidget(self.btn_speaker, 1)
        right_layout.addLayout(audio_btn_row)

        # Text Input Row
        input_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Or type a message here and press Enter…")
        self.text_input.returnPressed.connect(self._on_text_submitted)

        self.btn_send = QPushButton("Send")
        self.btn_send.setProperty("class", "secondary")
        self.btn_send.clicked.connect(self._on_text_submitted)

        input_row.addWidget(self.text_input, 1)
        input_row.addWidget(self.btn_send)
        right_layout.addLayout(input_row)

        main_layout.addWidget(right_card, 45)

    # ── Background Initialization ─────────────────────────────────────────────

    def _warm_voice_stack(self):
        """Pre-warm Whisper STT and Kokoro TTS in background."""
        try:
            from pywhispercpp.model import Model
            self.whisper_model = Model("base.en", print_realtime=False, print_progress=False)
            print("[VoiceChat] Whisper model loaded.", flush=True)
        except Exception as e:
            print(f"[VoiceChat] Whisper load error: {e}", flush=True)

        try:
            from jaeger_kokoro_tts.engine import KokoroTTS
            self.kokoro_tts = KokoroTTS()
            self.kokoro_tts.warm()
            print("[VoiceChat] Kokoro TTS engine ready.", flush=True)
        except Exception as e:
            print(f"[VoiceChat] Kokoro TTS error: {e}", flush=True)

    # ── Video Events ──────────────────────────────────────────────────────────

    def _on_frame_ready(self, q_img: QImage):
        scaled = q_img.scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.video_label.setPixmap(QPixmap.fromImage(scaled))

    def _on_switch_cam_clicked(self):
        new_idx = 1 if self.camera_worker.camera_index == 0 else 0
        self.camera_worker.stop()
        self.camera_worker = CameraWorker(camera_index=new_idx)
        self.camera_worker.frame_ready.connect(self._on_frame_ready)
        self.camera_worker.status_msg.connect(self.cam_badge.setText)
        self.camera_worker.start()

    def _on_snapshot_clicked(self):
        snap = self.camera_worker.get_snapshot()
        if snap is None:
            self._append_message("System", "Could not capture frame from camera.")
            return

        h, w, _ = snap.shape
        self._append_message("You", f"[Sent Camera Snapshot: {w}x{h} frame from Insta360 Link 2]")
        prompt = (
            f"The operator has shared a live camera frame ({w}x{h}) from their Insta360 Link 2 webcam. "
            "Acknowledge the visual input and greet the user warmly!"
        )
        self._send_to_ai(prompt)

    # ── Audio & Mic Logic ─────────────────────────────────────────────────────

    def _toggle_ptt(self):
        if not self.recorder.is_recording:
            self._start_listening()
        else:
            self._stop_listening_and_transcribe()

    def _start_listening(self):
        self.recorder.start()
        self.btn_ptt.setText("⏹ Stop Listening")
        self.btn_ptt.setProperty("class", "action_rec")
        self.btn_ptt.style().polish(self.btn_ptt)
        self.voice_orb.set_state("listening")
        self.lbl_stage_status.setText("Listening for speech…")

    def _stop_listening_and_transcribe(self):
        self.btn_ptt.setText("🎙 Push to Talk")
        self.btn_ptt.setProperty("class", "action")
        self.btn_ptt.style().polish(self.btn_ptt)
        self.voice_orb.set_state("thinking")
        self.lbl_stage_status.setText("Transcribing speech…")
        self.mic_bar.setValue(0)

        audio_data = self.recorder.stop()
        if len(audio_data) < 1600:  # < 0.1s
            self.voice_orb.set_state("idle")
            self.lbl_stage_status.setText("Ready · Tap to speak")
            return

        threading.Thread(target=self._process_audio_worker, args=(audio_data,), daemon=True).start()

    def _process_audio_worker(self, audio_data: np.ndarray):
        text = ""
        if self.whisper_model is not None:
            try:
                segments = self.whisper_model.transcribe(audio_data)
                cleaned = []
                for s in segments:
                    seg_text = getattr(s, "text", "").strip()
                    if seg_text and not seg_text.startswith("["):
                        cleaned.append(seg_text)
                text = " ".join(cleaned)
            except Exception as e:
                print(f"[STT] Transcribe error: {e}", flush=True)

        if not text.strip():
            QTimer.singleShot(0, lambda: self._on_transcription_empty())
            return

        QTimer.singleShot(0, lambda: self._on_transcription_done(text))

    def _on_transcription_empty(self):
        self.voice_orb.set_state("idle")
        self.lbl_stage_status.setText("No speech detected · Try again")

    def _on_transcription_done(self, text: str):
        self._append_message("You", text)
        self._send_to_ai(text)

    def _on_audio_tick(self):
        if self.recorder.is_recording:
            amp = self.recorder.current_amplitude
            self.voice_orb.set_amplitude(amp * 4.0)
            val = min(100, int(amp * 200))
            self.mic_bar.setValue(val)
        elif self.voice_orb.state == "speaking" and self.kokoro_tts is not None:
            amp = getattr(self.kokoro_tts, "amplitude", 0.0)
            self.voice_orb.set_amplitude(amp * 2.0)
        else:
            self.voice_orb.set_amplitude(0.0)

    # ── AI Brain Interaction ──────────────────────────────────────────────────

    def _on_text_submitted(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self._append_message("You", text)
        self._send_to_ai(text)

    def _send_to_ai(self, prompt: str):
        self.voice_orb.set_state("thinking")
        self.lbl_stage_status.setText("Iris is thinking…")

        def _worker():
            reply = ""
            if self.bridge_path is not None and self.bridge_path.exists():
                try:
                    client = BridgeTurnClient(self.bridge_path)
                    reply = client.send_turn(prompt)
                except Exception as e:
                    reply = f"(Bridge connection failed: {e})"
            else:
                reply = "I hear you loud and clear! (Bridge offline — local agent ready for voice test)."

            QTimer.singleShot(0, lambda: self._on_ai_reply(reply))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_ai_reply(self, reply: str):
        self._append_message("Iris", reply)
        self.voice_orb.set_state("speaking")
        self.lbl_stage_status.setText("Iris is speaking…")

        if self.speaker_enabled and self.kokoro_tts is not None:
            def _tts_worker():
                try:
                    self.kokoro_tts.speak(reply)
                except Exception as e:
                    print(f"[TTS] speak error: {e}", flush=True)
                QTimer.singleShot(0, self._on_speech_finished)

            threading.Thread(target=_tts_worker, daemon=True).start()
        else:
            QTimer.singleShot(1500, self._on_speech_finished)

    def _on_speech_finished(self):
        self.voice_orb.set_state("idle")
        self.lbl_stage_status.setText("Ready · Tap to speak")

    def _toggle_speaker(self):
        self.speaker_enabled = not self.speaker_enabled
        if self.speaker_enabled:
            self.btn_speaker.setText("🔊 Speaker: ON")
            self.btn_speaker.setStyleSheet("color: #3fb950;")
        else:
            self.btn_speaker.setText("🔇 Speaker: MUTED")
            self.btn_speaker.setStyleSheet("color: #8b949e;")

    def _append_message(self, sender: str, text: str):
        color = "#58a6ff" if sender == "You" else ("#3fb950" if sender == "Iris" else "#8b949e")
        self.transcript_area.append(f'<b style="color: {color};">{sender}:</b> {text}<br>')
        sb = self.transcript_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Key Bindings ──────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() and not self.text_input.hasFocus():
            if not self.recorder.is_recording:
                self._start_listening()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() and not self.text_input.hasFocus():
            if self.recorder.is_recording:
                self._stop_listening_and_transcribe()
            return
        super().keyReleaseEvent(event)

    def closeEvent(self, event):
        self.camera_worker.stop()
        if self.recorder.is_recording:
            self.recorder.stop()
        if self.kokoro_tts is not None:
            try:
                self.kokoro_tts.shutdown()
            except Exception:
                pass
        event.accept()


# ── Launcher ──────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    window = StandaloneVideoChatWindow()
    window.show()
    # Bring to front on macOS
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
