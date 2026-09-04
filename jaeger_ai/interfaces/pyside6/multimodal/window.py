"""JaegerAI's full multimodal face.

The window captures devices, pumps inputs, and renders engine Events.  All
endpointing, wake policy, transcription, LLM/tool work, speech synthesis, and
barge decisions remain in :mod:`jaeger_agent`.
"""

from __future__ import annotations

import base64
import html
import os
import queue
import threading
import time
from collections.abc import Callable
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import (
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoSink,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .worker import MultimodalWorker

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000
CAPTURE_DIR = Path.home() / ".jaeger" / "captures"

_CANVAS = "#0B0E14"
_PANEL = "#131720"
_INK = "#DDE2EA"
_INK_DIM = "#888F9C"
_RULE = "#21344A"
_ACCENT = "#3AA0FF"
_GREEN = "#43E08A"
_MONO = "SF Mono, Menlo, Consolas, monospace"

_VIRTUAL_CAM = ("obs", "virtual", "ndi", "camo", "snap", "loopback")


def _offer_audio(target: queue.Queue[np.ndarray], block: Any) -> None:
    """Update a bounded visual tap without blocking a device callback."""
    pcm = np.asarray(block, dtype=np.float32).reshape(-1).copy()
    try:
        target.put_nowait(pcm)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(pcm)
        except queue.Full:
            pass


def _drain_audio(source: queue.Queue[np.ndarray]) -> np.ndarray | None:
    blocks: list[np.ndarray] = []
    while True:
        try:
            blocks.append(source.get_nowait())
        except queue.Empty:
            break
    return np.concatenate(blocks) if blocks else None


def pick_camera(devices: Any) -> Any:
    """Prefer physical cameras while keeping the picker authoritative."""
    devices = list(devices)
    physical = [
        device
        for device in devices
        if not any(word in device.description().lower() for word in _VIRTUAL_CAM)
    ]
    pool = physical or devices
    for preferred in ("c920", "logi", "facetime", "built-in"):
        for device in pool:
            if preferred in device.description().lower():
                return device
    return pool[0] if pool else None


class Waveform(QWidget):
    """One-second logarithmic view of the real signed PCM."""

    def __init__(
        self,
        sample_rate: int,
        color: tuple[int, int, int] = (67, 224, 138),
    ) -> None:
        super().__init__()
        self.color = QColor(*color)
        self.capacity = max(256, sample_rate)
        self.samples: deque[float] = deque([0.0] * self.capacity, maxlen=self.capacity)
        self.setMinimumHeight(72)

    def push(self, block: Any) -> None:
        samples = np.asarray(block, dtype=np.float32).reshape(-1)
        if samples.size:
            self.samples.extend(samples.tolist())
            self.update()

    def clear(self) -> None:
        self.samples.clear()
        self.samples.extend([0.0] * self.capacity)
        self.update()

    def paintEvent(self, _event: Any) -> None:  # noqa: N802 — Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(_CANVAS))
        width, height = self.width(), self.height()
        middle = height / 2.0
        painter.setPen(QPen(QColor(_RULE), 1))
        painter.drawLine(0, int(middle), width, int(middle))
        if width < 2:
            return
        data = np.fromiter(self.samples, dtype=np.float32, count=len(self.samples))
        points = min(data.size, max(2, width))
        centers = np.linspace(0, data.size - 1, points).astype(np.int64)
        cumulative = np.concatenate(([0.0], np.cumsum(data, dtype=np.float64)))
        smooth = max(1, int(data.size * 0.004))
        starts = np.maximum(0, centers - smooth // 2)
        ends = np.minimum(data.size, starts + smooth)
        starts = np.maximum(0, ends - smooth)
        signed = (cumulative[ends] - cumulative[starts]) / np.maximum(1, ends - starts)

        squares = np.square(data, dtype=np.float64)
        energy = np.concatenate(([0.0], np.cumsum(squares)))
        rms_window = max(1, int(data.size * 0.015))
        rms_starts = np.maximum(0, centers - rms_window // 2)
        rms_ends = np.minimum(data.size, rms_starts + rms_window)
        rms_starts = np.maximum(0, rms_ends - rms_window)
        rms = np.sqrt(
            (energy[rms_ends] - energy[rms_starts])
            / np.maximum(1, rms_ends - rms_starts)
        )
        floor = 10.0 ** (-60.0 / 20.0)
        db = 20.0 * np.log10(np.maximum(rms, floor))
        gate_db = float(np.clip(np.percentile(db, 20.0) + 8.0, -50.0, -30.0))
        gate = np.clip((db - gate_db) / 10.0, 0.0, 1.0)
        gate = gate * gate * (3.0 - 2.0 * gate)
        gain = np.clip((db + 60.0) / 60.0, 0.0, 1.0)
        shape = np.clip(signed / np.maximum(rms * 1.5, floor), -1.0, 1.0)
        visible = shape * gain * gate

        path = QPainterPath()
        ys = np.clip(middle - visible * (middle - 2.0), 1.0, height - 2.0)
        path.moveTo(0.0, float(ys[0]))
        scale = (width - 1) / (points - 1)
        for index in range(1, points):
            path.lineTo(index * scale, float(ys[index]))
        painter.setPen(QPen(self.color, 1.35))
        painter.drawPath(path)


class CommitTicker(QWidget):
    """One mark per committed user/assistant event."""

    def __init__(self) -> None:
        super().__init__()
        self.decisions: deque[bool] = deque(maxlen=60)
        self.setMinimumHeight(28)

    def push(self, assistant: bool) -> None:
        self.decisions.append(assistant)
        self.update()

    def clear(self) -> None:
        self.decisions.clear()
        self.update()

    def paintEvent(self, _event: Any) -> None:  # noqa: N802 — Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_CANVAS))
        step = self.width() / self.decisions.maxlen
        painter.setPen(Qt.PenStyle.NoPen)
        for index, assistant in enumerate(self.decisions):
            painter.setBrush(QColor(_ACCENT if assistant else _GREEN))
            painter.drawRect(
                int(index * step) + 1,
                4,
                max(2, int(step) - 2),
                self.height() - 8,
            )


class MultimodalWindow(QMainWindow):
    """Camera, microphone, text, interaction log, and full telemetry."""

    camera_devices_ready = Signal(object, str)
    remote_agent_event = Signal(object)

    MODES = (
        ("Half-Duplex", "structured"),
        ("Quasi Full-Duplex", "quasi"),
        ("Full-Duplex", "full"),
    )
    TRANSCRIPT_COLORS = {
        "committed": _GREEN,
        "submitted": "#5AD2FF",
        "overheard": "#E5C94A",
        "environment": _INK_DIM,
        "self": "#FF6B6B",
    }

    def __init__(
        self,
        ctx: Any,
        *,
        engine_factory: Callable[..., Any] | None = None,
        main_surface: bool = False,
    ) -> None:
        super().__init__()
        self.ctx = ctx
        self._engine_factory = engine_factory
        self._main_surface = main_surface
        self.worker: MultimodalWorker | None = None
        self.mic_stream: Any = None
        self.camera: QCamera | None = None
        self.capture: QMediaCaptureSession | None = None
        self.video_sink: QVideoSink | None = None
        self._camera_devices: list[Any] = []
        self._camera_discovery_started = False
        self._camera_enable_pending = False
        self._last_jpeg = 0.0
        self._mic_waveform_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)
        self._agent_waveform_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)
        self._recorded: list[np.ndarray] = []
        self._record_enabled = False
        self._commit_count = 0
        self._now_text = "idle"
        self._now_since = time.monotonic()
        self._task_started_at = 0.0
        self._task_count = 0
        self._turn_tool_count = 0
        self._turn_tool_time = 0.0
        self._last_task_total = 0.0
        self._active_tools: dict[str, list[float]] = {}
        self._workspace_bridge: Any = None
        self._workspace_session = "multimodal"

        self.setObjectName("MultimodalWindow")
        self.setWindowTitle("Jaeger AI — Multimodal")
        self.resize(1760, 900)
        self.remote_agent_event.connect(self._on_remote_agent_event)
        runtime = self._runtime()
        set_event_sink = getattr(runtime, "set_event_sink", None)
        if callable(set_event_sink):
            set_event_sink(self.remote_agent_event.emit)
        self._build_ui()
        self.camera_devices_ready.connect(self._on_camera_devices_ready)
        self._begin_camera_discovery()
        self._apply_style()
        self._connect_workspace_bus()
        initial_mode = os.environ.get("JAEGER_MULTIMODAL_AUDIO_MODE", "structured")
        if initial_mode == "plain":
            self.mode_box.insertItem(0, "Plain (CLI)", "plain")
        selected = self.mode_box.findData(initial_mode)
        if selected >= 0:
            self.mode_box.setCurrentIndex(selected)

        self._paint_timer = QTimer(self)
        self._paint_timer.setInterval(50)
        self._paint_timer.timeout.connect(self._paint_waveforms)
        self._paint_timer.start()
        self._now_timer = QTimer(self)
        self._now_timer.setInterval(100)
        self._now_timer.timeout.connect(self._paint_now)
        self._now_timer.start()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("MULTIMODAL")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addWidget(QLabel("camera · microphone · text → Jaeger Agent"))
        header.addStretch(1)
        header.addWidget(QLabel("Audio pipeline"))
        self.mode_box = QComboBox()
        for label, mode in self.MODES:
            self.mode_box.addItem(label, mode)
        self.mode_box.currentIndexChanged.connect(self._mode_changed)
        header.addWidget(self.mode_box)
        header.addWidget(QLabel("Barge"))
        self.barge_box = QComboBox()
        self.barge_box.addItem("stop — yield the floor", "stop")
        self.barge_box.addItem("continue — finish reply", "continue")
        self.barge_box.currentIndexChanged.connect(self._barge_changed)
        header.addWidget(self.barge_box)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._input_panel())
        splitter.addWidget(self._agent_panel())
        splitter.addWidget(self._telemetry_panel())
        splitter.addWidget(self._workspace_panel())
        splitter.setSizes([410, 450, 300, 480])
        root.addWidget(splitter, stretch=1)

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.force_btn = QPushButton("Force Listen")
        self.force_btn.clicked.connect(self._force_listen)
        self.mic_check = QPushButton("Mic: On")
        self.mic_check.setCheckable(True)
        self.mic_check.setChecked(True)
        self.mic_check.setToolTip("Mute or enable microphone input; on by default.")
        self.mic_check.toggled.connect(self._mic_enabled_changed)
        self.record_check = QCheckBox("Record")
        self.record_check.toggled.connect(self._set_record_enabled)
        for widget in (
            self.force_btn,
            self.mic_check,
            self.record_check,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)
        root.addLayout(controls)
        self.status_label = QLabel("Attaching to the running Jaeger AI agent…")
        self.status_label.setObjectName("Status")
        root.addWidget(self.status_label)
        self._set_running_controls(False)

    def _input_panel(self) -> QWidget:
        panel = QGroupBox("INPUT")
        layout = QVBoxLayout(panel)
        self.camera_label = QLabel("camera off")
        self.camera_label.setObjectName("Camera")
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setMinimumHeight(250)
        layout.addWidget(self.camera_label, stretch=3)
        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel("Camera"))
        self.camera_box = QComboBox()
        self.camera_box.setEnabled(False)
        self.camera_box.currentIndexChanged.connect(self._reopen_camera)
        camera_row.addWidget(self.camera_box, stretch=1)
        layout.addLayout(camera_row)
        self.video_check = QCheckBox(
            "send video — 1 frame/s through the vision projector"
        )
        self.video_check.toggled.connect(self._toggle_camera)
        layout.addWidget(self.video_check)
        layout.addWidget(QLabel("Microphone — 1 s · logarithmic −60 to 0 dBFS"))
        self.user_waveform = Waveform(SAMPLE_RATE)
        layout.addWidget(self.user_waveform)
        layout.addWidget(QLabel("Optional extra system prompt"))
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("Applied when the session starts")
        layout.addWidget(self.prompt_edit)
        typed_row = QHBoxLayout()
        self.typed_edit = QLineEdit()
        self.typed_edit.setPlaceholderText(
            "Type a message — Enter sends; no wake phrase"
        )
        self.typed_edit.returnPressed.connect(self._send_typed)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_typed)
        self.attach_btn = QPushButton("Attach Image")
        self.attach_btn.clicked.connect(self._attach_image)
        self.agentic_check = QPushButton("Mode: Agentic")
        self.agentic_check.setObjectName("AgentMode")
        self.agentic_check.setCheckable(True)
        self.agentic_check.setChecked(True)
        self.agentic_check.setToolTip(
            "Agentic uses memory/tools; Chatbot uses the same Gemma with tools disabled."
        )
        self.agentic_check.toggled.connect(self._agent_mode_changed)
        typed_row.addWidget(self.typed_edit, stretch=1)
        typed_row.addWidget(self.attach_btn)
        typed_row.addWidget(self.agentic_check)
        typed_row.addWidget(self.send_btn)
        layout.addLayout(typed_row)
        return panel

    def _agent_panel(self) -> QWidget:
        panel = QGroupBox("AGENT — interaction log")
        layout = QVBoxLayout(panel)
        self.ticker_label = QLabel("0 committed events")
        layout.addWidget(self.ticker_label)
        self.ticker = CommitTicker()
        layout.addWidget(self.ticker)
        layout.addWidget(QLabel("Agent voice — real output waveform"))
        self.agent_waveform = Waveform(TTS_SAMPLE_RATE, color=(58, 160, 255))
        layout.addWidget(self.agent_waveform)
        layout.addWidget(QLabel("You / Assistant"))
        self.conversation = QTextEdit()
        self.conversation.setReadOnly(True)
        layout.addWidget(self.conversation, stretch=1)
        self.summary_label = QLabel("—")
        self.summary_label.setObjectName("Dim")
        layout.addWidget(self.summary_label)
        return panel

    def _telemetry_panel(self) -> QWidget:
        panel = QGroupBox("TELEMETRY")
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("SESSION"))
        self.telemetry_rows: dict[str, QLabel] = {}
        for key, initial in (
            ("Wake phrase", "hey jaeger"),
            ("Wake", "—"),
            ("Mode", "—"),
            ("Model", "—"),
            ("Microphone", "—"),
            ("Gate", "—"),
            ("Audio", "—"),
            ("Barge", "stop"),
            ("Agent", "AGENTIC"),
            ("Output", "DYNAMIC"),
            ("Endpoint", "500 ms silence"),
            ("Now", "idle  0.0s"),
        ):
            row = QHBoxLayout()
            name = QLabel(key)
            name.setObjectName("RowName")
            name.setFixedWidth(94)
            value = QLabel(initial)
            value.setWordWrap(True)
            row.addWidget(name)
            row.addWidget(value, stretch=1)
            layout.addLayout(row)
            self.telemetry_rows[key] = value
        layout.addWidget(QLabel("LIVE — forming now"))
        self.live_label = QLabel("—")
        self.live_label.setObjectName("Live")
        self.live_label.setWordWrap(True)
        self.live_label.setMinimumHeight(42)
        layout.addWidget(self.live_label)
        layout.addWidget(QLabel("TRANSCRIPT — everything heard"))
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMinimumHeight(150)
        layout.addWidget(self.transcript, stretch=1)
        layout.addWidget(QLabel("LATENCY"))
        self.latency_rows: dict[str, QLabel] = {}
        for key in ("Speech detected", "End-of-turn", "Reply ready", "Spoken"):
            row = QHBoxLayout()
            name = QLabel(key)
            name.setObjectName("RowName")
            name.setFixedWidth(112)
            value = QLabel("—")
            row.addWidget(name)
            row.addWidget(value, stretch=1)
            layout.addLayout(row)
            self.latency_rows[key] = value
        panel.setMinimumWidth(300)
        return panel

    def _workspace_panel(self) -> QWidget:
        panel = QGroupBox("AGENTIC WORKSPACE")
        layout = QVBoxLayout(panel)

        heading = QHBoxLayout()
        heading.addWidget(QLabel("LIVE TASK OBSERVABILITY"))
        heading.addStretch(1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_workspace)
        heading.addWidget(clear)
        layout.addLayout(heading)

        self.workspace_rows: dict[str, QLabel] = {}
        for key, initial in (
            ("Tasks", "0"),
            ("Task elapsed", "—"),
            ("Reply latency", "—"),
            ("Tools", "0"),
            ("Tool time", "0.00 s"),
            ("Agent/model", "—"),
        ):
            row = QHBoxLayout()
            name = QLabel(key)
            name.setObjectName("RowName")
            name.setFixedWidth(105)
            value = QLabel(initial)
            row.addWidget(name)
            row.addWidget(value, stretch=1)
            layout.addLayout(row)
            self.workspace_rows[key] = value

        layout.addWidget(QLabel("REASONING ACTIVITY — observable summaries"))
        self.reasoning_activity = QTextEdit()
        self.reasoning_activity.setObjectName("WorkspaceLog")
        self.reasoning_activity.setReadOnly(True)
        self.reasoning_activity.setPlaceholderText(
            "High-level agent status appears here; private chain-of-thought is not exposed."
        )
        layout.addWidget(self.reasoning_activity, stretch=2)

        layout.addWidget(QLabel("TOOL CHAIN"))
        self.tool_chain = QTextEdit()
        self.tool_chain.setObjectName("WorkspaceLog")
        self.tool_chain.setReadOnly(True)
        self.tool_chain.setPlaceholderText(
            "Tool start, completion, error, and duration"
        )
        layout.addWidget(self.tool_chain, stretch=2)

        layout.addWidget(QLabel("TOOL OUTPUTS"))
        self.tool_outputs = QTextEdit()
        self.tool_outputs.setObjectName("WorkspaceLog")
        self.tool_outputs.setReadOnly(True)
        self.tool_outputs.setPlaceholderText("Redacted, bounded result previews")
        layout.addWidget(self.tool_outputs, stretch=2)

        layout.addWidget(QLabel("FILES / ARTIFACTS"))
        self.artifacts = QTextEdit()
        self.artifacts.setObjectName("WorkspaceLog")
        self.artifacts.setReadOnly(True)
        self.artifacts.setPlaceholderText("Created or returned file paths")
        self.artifacts.setMaximumHeight(110)
        layout.addWidget(self.artifacts, stretch=1)
        panel.setMinimumWidth(390)
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow#MultimodalWindow, QWidget {{
                background: {_CANVAS}; color: {_INK};
                font-family: {_MONO}; font-size: 12px;
            }}
            QLabel#Title {{ color: {_ACCENT}; font-size: 18px; font-weight: 800; }}
            QLabel#Dim, QLabel#RowName {{ color: {_INK_DIM}; }}
            QLabel#Live {{ color: #E5C94A; font-style: italic; }}
            QLabel#Status {{ color: #8AAFC9; padding: 4px 8px; }}
            QLabel#Camera {{ background: #080A0F; color: {_INK_DIM};
                border: 1px solid {_RULE}; border-radius: 8px; }}
            QGroupBox {{ background: {_PANEL}; border: 1px solid {_RULE};
                border-radius: 10px; margin-top: 12px; padding-top: 10px;
                font-weight: 700; }}
            QGroupBox::title {{ color: {_ACCENT}; subcontrol-origin: margin;
                left: 10px; padding: 0 5px; }}
            QTextEdit, QLineEdit, QComboBox {{ background: #0E121A;
                border: 1px solid {_RULE}; border-radius: 7px;
                padding: 7px; color: {_INK}; }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
                border-color: {_ACCENT}; }}
            QPushButton {{ background: #182231; border: 1px solid {_RULE};
                border-radius: 7px; padding: 7px 12px; }}
            QPushButton:hover {{ border-color: {_ACCENT}; }}
            QPushButton#Primary {{ background: {_ACCENT}; color: white;
                font-weight: 700; }}
            QPushButton#AgentMode {{ min-width: 112px; font-weight: 700; }}
            QPushButton#AgentMode:checked {{ background: #174D38; color: {_GREEN};
                border-color: {_GREEN}; }}
            QPushButton:disabled {{ color: #59616D; background: #111720; }}
            QTextEdit#WorkspaceLog {{ font-size: 11px; padding: 5px; }}
            QSplitter::handle {{ background: {_RULE}; width: 1px; }}
            """
        )

    def current_audio_mode(self) -> str:
        return str(self.mode_box.currentData() or "structured")

    def current_barge_mode(self) -> str:
        return str(self.barge_box.currentData() or "stop")

    def current_agentic_tools(self) -> bool:
        return self.agentic_check.isChecked()

    def _runtime(self) -> Any:
        core = getattr(self.ctx, "core", None)
        return getattr(core, "runtime", None)

    def _connect_workspace_bus(self) -> None:
        bus = getattr(self.ctx, "bus", None)
        if bus is None:
            return
        try:
            from jaeger_os.app.surfaces import make_bus_bridge

            self._workspace_bridge = make_bus_bridge(
                bus,
                ["/sense/tool", "/sense/activity", "/sense/agent_state"],
            )
            self._workspace_bridge.message.connect(self._on_agent_event)
        except Exception as exc:  # noqa: BLE001 — workspace is optional observability
            self._append_workspace(
                self.reasoning_activity,
                "monitor",
                f"bus activity unavailable: {type(exc).__name__}: {exc}",
                "#FF6B6B",
            )

    def start_session(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        runtime = self._runtime()
        if runtime is None and self._engine_factory is None:
            self._set_status("FAILED: the JaegerAI AgentRuntime is not available")
            return
        self._commit_count = 0
        self.conversation.clear()
        self.transcript.clear()
        self.ticker.clear()
        self.user_waveform.clear()
        self.agent_waveform.clear()
        self._clear_workspace()
        self._recorded = []
        self.worker = MultimodalWorker(
            runtime=runtime,
            engine_factory=self._engine_factory,
            want_vision=True,
            extra_prompt=self.prompt_edit.text().strip(),
            audio_mode=self.current_audio_mode(),
            barge_mode=self.current_barge_mode(),
            agentic_tools=self.current_agentic_tools(),
        )
        brain = getattr(self.worker.engine, "node_llm", None)
        self._workspace_session = str(getattr(brain, "session_key", "") or "multimodal")
        self.worker.commit.connect(self._on_commit)
        self.worker.output.connect(self._on_output_decision)
        self.worker.summary.connect(self.summary_label.setText)
        self.worker.status.connect(self._set_status)
        self.worker.ready.connect(self._on_ready)
        self.worker.failed.connect(self._on_failed)
        self.worker.telem.connect(self._on_telemetry)
        self.worker.lat.connect(self._on_latency)
        self.worker.live.connect(self._on_live)
        self.worker.tscript.connect(self._on_transcript)
        self.worker.spoke.connect(self._on_spoke)
        self.worker.heard.connect(self._on_heard)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()
        self._set_running_controls(True)
        self._set_status(f"Loading {self.current_audio_mode()} audio pipeline…")

    def stop_session(self) -> bool:
        self._close_microphone()
        worker = self.worker
        if worker is not None:
            worker.stop()
            if worker.isRunning() and not worker.wait(10_000):
                self._set_status("Worker still stopping after 10 s")
                self._save_recording()
                return False
            self.worker = None
        self._save_recording()
        self._set_running_controls(False)
        self._on_telemetry("Now", "idle")
        return True

    def _on_ready(self) -> None:
        worker = self.worker
        if worker is not None and worker.gui_feeds_audio and self.mic_check.isChecked():
            self._open_microphone()
        else:
            self._set_status("Engine-owned 48 kHz AEC device is active")
        self.force_btn.setEnabled(True)

    def _on_finished(self) -> None:
        sender = self.sender()
        if sender is self.worker:
            self.worker = None
        self._set_running_controls(False)

    def _on_failed(self, message: str) -> None:
        self._set_status(f"FAILED: {message}")
        self._close_microphone()
        self._set_running_controls(False)

    def _set_running_controls(self, running: bool) -> None:
        self.mic_check.setEnabled(running)
        self.force_btn.setEnabled(False if not running else self.force_btn.isEnabled())
        self.prompt_edit.setEnabled(not running)
        self.agentic_check.setEnabled(True)
        self.mode_box.setEnabled(True)

    def _agent_mode_changed(self, enabled: bool) -> None:
        mode = "Agentic tools" if enabled else "Gemma chatbot"
        self.agentic_check.setText("Mode: Agentic" if enabled else "Mode: Chatbot")
        self._on_telemetry("Agent", "AGENTIC" if enabled else "CHATBOT")
        self._on_telemetry("Output", "DYNAMIC" if enabled else "SPEECH")
        self._append_workspace(
            self.reasoning_activity,
            "mode",
            (
                "Agentic monitoring enabled"
                if enabled
                else "Chatbot mode selected; tool execution is disabled"
            ),
            _GREEN if enabled else _INK_DIM,
        )
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.set_agentic_tools(enabled)
        self._set_status(f"{mode} active")

    def _mode_changed(self, _index: int) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._set_status(f"Switching to {self.mode_box.currentText()}…")
            if self.stop_session():
                self.start_session()
        else:
            self._set_status(
                f"{self.mode_box.currentText()} selected for the next session"
            )

    def _barge_changed(self, _index: int) -> None:
        mode = self.current_barge_mode()
        if self.worker is not None and self.worker.isRunning():
            try:
                self.worker.set_barge_mode(mode)
            except Exception as exc:  # noqa: BLE001 — render control failure
                self._set_status(f"Barge control failed: {exc}")
        self._on_telemetry("Barge", mode)

    def _mic_enabled_changed(self, enabled: bool) -> None:
        self.mic_check.setText("Mic: On" if enabled else "Mic: Muted")
        worker = self.worker
        if worker is not None and worker.isRunning():
            try:
                worker.set_paused(not enabled)
                if worker.gui_feeds_audio:
                    if enabled:
                        self._open_microphone()
                    else:
                        self._close_microphone()
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"Microphone control failed: {exc}")
        self._on_telemetry("Microphone", "ON" if enabled else "MUTED")

    def _force_listen(self) -> None:
        if self.worker is None:
            return
        try:
            self.worker.force_listen()
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Force Listen failed: {exc}")

    def _send_typed(self) -> None:
        text = self.typed_edit.text().strip()
        if not text:
            return
        worker = self.worker
        if worker is None or not worker.isRunning():
            self._set_status("The multimodal face is still attaching")
            return
        self.typed_edit.clear()
        worker.submit_text(text)

    def _attach_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        worker = self.worker
        if worker is None or not worker.isRunning():
            self._set_status("The multimodal face is still attaching")
            return
        suffix = Path(path).suffix.lower()
        mime = "image/png" if suffix == ".png" else (
            "image/webp" if suffix == ".webp" else "image/jpeg"
        )
        try:
            payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError as exc:
            self._set_status(f"Could not attach image: {exc}")
            return
        worker.submit_image(f"data:{mime};base64,{payload}")
        self._set_status(f"Attached {Path(path).name} to the next turn")

    def _open_microphone(self) -> None:
        if self.mic_stream is not None:
            return
        try:
            import sounddevice as sd

            self.mic_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=SAMPLE_RATE // 10,
                callback=self._microphone_callback,
            )
            self.mic_stream.start()
            device = sd.query_devices(sd.default.device[0])["name"]
            self._on_telemetry("Microphone", str(device))
            self._set_status(f"Microphone active: {device}")
        except Exception as exc:  # noqa: BLE001 — device failure belongs in status
            self.mic_stream = None
            self._set_status(f"MICROPHONE FAILED: {type(exc).__name__}: {exc}")

    def _close_microphone(self) -> None:
        if self.mic_stream is None:
            return
        try:
            self.mic_stream.stop()
            self.mic_stream.close()
        except Exception:  # noqa: BLE001 — teardown never blocks close
            pass
        self.mic_stream = None

    def _microphone_callback(
        self,
        input_data: Any,
        _frames: int,
        _time_info: Any,
        _status: Any,
    ) -> None:
        mono = np.asarray(input_data[:, 0], dtype=np.float32).copy()
        _offer_audio(self._mic_waveform_q, mono)
        if self._record_enabled:
            self._recorded.append(mono)
        worker = self.worker
        if (
            worker is not None
            and worker.isRunning()
            and worker.gui_feeds_audio
            and self.mic_check.isChecked()
        ):
            worker.audio_q.put(mono)

    def _on_heard(self, pcm: Any) -> None:
        _offer_audio(self._mic_waveform_q, pcm)
        if self._record_enabled:
            self._recorded.append(np.asarray(pcm, dtype=np.float32).reshape(-1).copy())

    def _set_record_enabled(self, enabled: bool) -> None:
        self._record_enabled = enabled

    def _on_spoke(self, pcm: Any) -> None:
        _offer_audio(self._agent_waveform_q, pcm)

    def _paint_waveforms(self) -> None:
        user_pcm = _drain_audio(self._mic_waveform_q)
        if user_pcm is not None:
            self.user_waveform.push(user_pcm)
        agent_pcm = _drain_audio(self._agent_waveform_q)
        if agent_pcm is not None:
            # Engine Events arrive one generated chunk at a time, so this is
            # already live output rather than a synthetic animation.
            self.agent_waveform.push(agent_pcm)

    def _save_recording(self) -> None:
        if not self._recorded:
            return
        try:
            import soundfile as sf

            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            path = CAPTURE_DIR / time.strftime("multimodal_%Y%m%d_%H%M%S.wav")
            sf.write(path, np.concatenate(self._recorded), SAMPLE_RATE)
            self._set_status(f"Recording saved: {path}")
        except Exception as exc:  # noqa: BLE001 — report optional recorder failure
            self._set_status(f"Recording save failed: {type(exc).__name__}: {exc}")
        finally:
            self._recorded = []

    def _on_commit(self, _index: int, role: str, text: str) -> None:
        self._commit_count += 1
        who = "You" if role == "user" else "Assistant"
        color = _GREEN if role == "user" else _ACCENT
        safe = html.escape(text).replace("\n", "<br>")
        self.conversation.append(f'<p><b style="color:{color}">{who}:</b> {safe}</p>')
        self.ticker.push(role == "assistant")
        self.ticker_label.setText(f"{self._commit_count} committed events")
        if role == "user":
            self._task_started_at = time.monotonic()
            self._turn_tool_count = 0
            self._turn_tool_time = 0.0
            self._last_task_total = 0.0
            self._active_tools.clear()
            self.workspace_rows["Tools"].setText("0")
            self.workspace_rows["Tool time"].setText("0.00 s")
            self.workspace_rows["Agent/model"].setText("running…")
            self._append_workspace(
                self.reasoning_activity,
                "task",
                "Turn submitted to the agent",
                _GREEN,
            )

    def _on_output_decision(self, channels: str, data: Any) -> None:
        """Render the agent's chosen channels and close even non-text turns."""
        self._on_telemetry("Output", channels)
        metadata = data if isinstance(data, dict) else {}
        source = str(metadata.get("source") or "engine")
        self._append_workspace(
            self.reasoning_activity,
            "output",
            f"{channels} · {source}",
            _ACCENT if channels != "SILENT" else _INK_DIM,
        )
        self._finish_workspace_task()

    def _finish_workspace_task(self) -> None:
        if not self._task_started_at:
            return
        total = time.monotonic() - self._task_started_at
        self._last_task_total = total
        self._task_count += 1
        self.workspace_rows["Tasks"].setText(str(self._task_count))
        self.workspace_rows["Task elapsed"].setText(f"{total:.2f} s")
        self.workspace_rows["Tool time"].setText(f"{self._turn_tool_time:.2f} s")
        self.workspace_rows["Agent/model"].setText(
            f"{max(0.0, total - self._turn_tool_time):.2f} s"
        )
        self._append_workspace(
            self.reasoning_activity,
            "task",
            f"Completed in {total:.2f} s with {self._turn_tool_count} tool call(s)",
            _ACCENT,
        )
        self._task_started_at = 0.0

    @staticmethod
    def _append_workspace(
        target: QTextEdit,
        label: str,
        text: str,
        color: str = _INK,
    ) -> None:
        timestamp = time.strftime("%H:%M:%S")
        safe_label = html.escape(label)
        safe_text = html.escape(str(text)).replace("\n", "<br>")
        target.append(
            f'<span style="color:{_INK_DIM}">{timestamp}</span> '
            f'<b style="color:{color}">{safe_label}</b> {safe_text}'
        )
        scrollbar = target.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_workspace(self) -> None:
        for target in (
            self.reasoning_activity,
            self.tool_chain,
            self.tool_outputs,
            self.artifacts,
        ):
            target.clear()
        self._task_started_at = 0.0
        self._task_count = 0
        self._turn_tool_count = 0
        self._turn_tool_time = 0.0
        self._last_task_total = 0.0
        self._active_tools.clear()
        for key, value in (
            ("Tasks", "0"),
            ("Task elapsed", "—"),
            ("Reply latency", "—"),
            ("Tools", "0"),
            ("Tool time", "0.00 s"),
            ("Agent/model", "—"),
        ):
            self.workspace_rows[key].setText(value)

    def _on_agent_event(self, message: Any) -> None:
        session = str(getattr(message, "session", "") or "")
        base_session = self._workspace_session.split(":", 1)[0]
        if session and session.split(":", 1)[0] != base_session:
            return
        topic = str(getattr(message, "topic", ""))
        if topic == "/sense/tool":
            self._on_tool_event(message)
        elif topic == "/sense/activity":
            kind = str(getattr(message, "kind", "status") or "status")
            text = str(getattr(message, "text", "") or "").strip()
            if not text:
                return
            if kind == "artifact":
                self._append_workspace(self.artifacts, "file", text, _GREEN)
            else:
                self._append_workspace(
                    self.reasoning_activity,
                    "tool selected" if kind == "tool" else kind,
                    text,
                    _ACCENT if kind == "tool" else _INK_DIM,
                )
        elif topic == "/sense/agent_state":
            state = str(getattr(message, "state", "status") or "status")
            detail = str(getattr(message, "detail", "") or "").strip()
            self._append_workspace(
                self.reasoning_activity,
                "state",
                f"{state}{(': ' + detail) if detail else ''}",
                "#FF6B6B" if state == "error" else _INK_DIM,
            )

    def _on_remote_agent_event(self, frame: object) -> None:
        """Translate bridge wire telemetry into the existing workspace feed."""
        if not isinstance(frame, dict):
            return
        kind = str(frame.get("type") or "")
        if kind == "tool":
            self._on_agent_event(
                SimpleNamespace(
                    topic="/sense/tool",
                    name=frame.get("name", ""),
                    phase=frame.get("phase", "start"),
                    detail=frame.get("detail", ""),
                    elapsed_s=frame.get("elapsed_s", 0.0),
                    session=frame.get("session", ""),
                )
            )
        elif kind == "agent_event":
            values = dict(frame)
            values.pop("type", None)
            self._on_agent_event(SimpleNamespace(**values))

    def _on_tool_event(self, message: Any) -> None:
        name = str(getattr(message, "name", "") or "tool")
        phase = str(getattr(message, "phase", "start") or "start")
        detail = str(getattr(message, "detail", "") or "").strip()
        elapsed = float(getattr(message, "elapsed_s", 0.0) or 0.0)
        if phase == "start":
            self._turn_tool_count += 1
            self._active_tools.setdefault(name, []).append(time.monotonic())
            self.workspace_rows["Tools"].setText(str(self._turn_tool_count))
            suffix = f" — {detail}" if detail else ""
            self._append_workspace(self.tool_chain, "start", name + suffix, _ACCENT)
            return
        if phase in {"output", "error-output"}:
            self._append_workspace(
                self.tool_outputs,
                name,
                detail or "(no output)",
                "#FF6B6B" if phase == "error-output" else _GREEN,
            )
            return

        starts = self._active_tools.get(name, [])
        started = starts.pop(0) if starts else 0.0
        if not starts:
            self._active_tools.pop(name, None)
        if elapsed <= 0.0 and started:
            elapsed = time.monotonic() - started
        self._turn_tool_time += max(0.0, elapsed)
        self.workspace_rows["Tool time"].setText(f"{self._turn_tool_time:.2f} s")
        if self._last_task_total:
            self.workspace_rows["Agent/model"].setText(
                f"{max(0.0, self._last_task_total - self._turn_tool_time):.2f} s"
            )
        suffix = f" — {detail}" if detail else ""
        self._append_workspace(
            self.tool_chain,
            phase,
            f"{name} · {elapsed:.2f} s{suffix}",
            "#FF6B6B" if "error" in phase else _GREEN,
        )

    def _on_transcript(self, disposition: str, text: str) -> None:
        color = self.TRANSCRIPT_COLORS[disposition]
        timestamp = time.strftime("%H:%M:%S")
        safe = html.escape(text).replace("\n", "<br>")
        self.transcript.append(
            f'<span style="color:{_INK_DIM}">{timestamp}</span> '
            f'<span style="color:{color}">{disposition:<11}</span> {safe}'
        )
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_telemetry(self, key: str, value: str) -> None:
        if key == "Now":
            changed = value != self._now_text
            self._now_text = value
            self._now_since = time.monotonic()
            if changed and value in {"thinking", "transcribing", "speaking"}:
                self._append_workspace(
                    self.reasoning_activity, "pipeline", value, _INK_DIM
                )
        row = self.telemetry_rows.get(key)
        if row is not None:
            row.setText(value)

    def _paint_now(self) -> None:
        self.telemetry_rows["Now"].setText(
            f"{self._now_text}  {time.monotonic() - self._now_since:.1f}s"
        )
        if self._task_started_at:
            self.workspace_rows["Task elapsed"].setText(
                f"{time.monotonic() - self._task_started_at:.1f} s"
            )

    def _on_live(self, text: str) -> None:
        self.live_label.setText(text or "—")

    def _on_latency(self, key: str, milliseconds: Any) -> None:
        row = self.latency_rows.get(key)
        if row is not None:
            row.setText(
                "—" if milliseconds is None else f"{float(milliseconds):,.0f} ms"
            )
        if key == "Reply ready" and milliseconds is not None:
            self.workspace_rows["Reply latency"].setText(
                f"{float(milliseconds):,.0f} ms"
            )

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _selected_camera(self, devices: Any) -> Any:
        selected = self.camera_box.currentText()
        for device in devices:
            if device.description() == selected:
                return device
        return pick_camera(devices)

    def _begin_camera_discovery(self) -> None:
        """Enumerate cameras without ever parking the Qt event loop."""
        if self._camera_discovery_started:
            return
        self._camera_discovery_started = True
        if (
            os.environ.get("JAEGER_TEST_HEADLESS") == "1"
            or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        ):
            self.camera_label.setText("camera disabled in headless mode")
            return

        def discover() -> None:
            try:
                devices = list(QMediaDevices.videoInputs())
            except Exception as exc:  # noqa: BLE001 — native device boundary
                self.camera_devices_ready.emit([], f"{type(exc).__name__}: {exc}")
            else:
                self.camera_devices_ready.emit(devices, "")

        threading.Thread(
            target=discover,
            name="multimodal-camera-discovery",
            daemon=True,
        ).start()

    def _on_camera_devices_ready(self, devices: Any, error: str) -> None:
        self._camera_devices = list(devices or [])
        self.camera_box.blockSignals(True)
        self.camera_box.clear()
        for device in self._camera_devices:
            self.camera_box.addItem(device.description())
        preferred = pick_camera(self._camera_devices)
        if preferred is not None:
            self.camera_box.setCurrentText(preferred.description())
        self.camera_box.setEnabled(bool(self._camera_devices))
        self.camera_box.blockSignals(False)
        if not self._camera_devices:
            self.camera_label.setText(
                f"camera unavailable: {error}" if error else "no camera found"
            )
            self._camera_enable_pending = False
            self.video_check.setChecked(False)
            return
        self.camera_label.setText("camera off")
        if self._camera_enable_pending or self.video_check.isChecked():
            self._camera_enable_pending = False
            self._open_selected_camera()

    def _open_selected_camera(self) -> None:
        camera = self._selected_camera(self._camera_devices)
        if camera is None:
            self.camera_label.setText("no camera found")
            self.video_check.setChecked(False)
            return
        self.camera = QCamera(camera)
        self.camera_label.setText(f"starting {camera.description()}…")
        self.camera.errorOccurred.connect(
            lambda _error, message: self.camera_label.setText(
                f"camera error: {message}"
            )
        )
        self.capture = QMediaCaptureSession()
        self.video_sink = QVideoSink()
        self.capture.setCamera(self.camera)
        self.capture.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self._on_video_frame)
        self.camera.start()

    def _toggle_camera(self, enabled: bool) -> None:
        if not enabled:
            self._camera_enable_pending = False
            self._close_camera()
            return
        if not self._camera_devices:
            self._camera_enable_pending = True
            self.camera_label.setText("discovering cameras…")
            self._begin_camera_discovery()
            return
        self._open_selected_camera()

    def _reopen_camera(self, _index: int) -> None:
        if self.video_check.isChecked():
            self._close_camera()
            self._toggle_camera(True)

    def _close_camera(self) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
            except Exception:  # noqa: BLE001
                pass
        self.camera = None
        self.capture = None
        self.video_sink = None
        self.camera_label.setPixmap(QPixmap())
        self.camera_label.setText("camera off")

    def _on_video_frame(self, frame: Any) -> None:
        image: QImage = frame.toImage()
        if image.isNull():
            return
        self.camera_label.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.camera_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        worker = self.worker
        now = time.monotonic()
        if (
            worker is not None
            and worker.isRunning()
            and self.video_check.isChecked()
            and now - self._last_jpeg >= 1.0
        ):
            self._last_jpeg = now
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.scaledToWidth(448, Qt.TransformationMode.SmoothTransformation).save(
                buffer, "JPG", 85
            )
            uri = "data:image/jpeg;base64," + base64.b64encode(
                bytes(buffer.data())
            ).decode("ascii")
            worker.submit_image(uri)

    def showEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        super().showEvent(event)
        if not getattr(self, "_opened_once", False):
            self._opened_once = True
            QTimer.singleShot(0, self.start_session)
            QTimer.singleShot(100, lambda: self.video_check.setChecked(True))

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        if not self.stop_session():
            # Keep the QObject alive while an in-flight model turn unwinds;
            # destroying a running QThread terminates the process in Qt.
            event.ignore()
            return
        self._close_camera()
        if self._main_surface:
            event.accept()
        else:
            event.ignore()
            self.hide()


def make_surface(ctx: Any, spec: Any = None) -> MultimodalWindow:
    return MultimodalWindow(ctx, main_surface=bool(getattr(spec, "main", False)))


__all__ = ["MultimodalWindow", "Waveform", "make_surface", "pick_camera"]
