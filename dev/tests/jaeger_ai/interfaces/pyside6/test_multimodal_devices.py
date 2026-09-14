"""Device lifecycle and preview regressions; no real models or devices."""

from __future__ import annotations

import os
import queue
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from jaeger_ai.interfaces.pyside6.multimodal import window as module

pytestmark = pytest.mark.ui


@pytest.fixture
def face(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module.MultimodalWindow, "_begin_camera_discovery", lambda _: None)
    window = module.MultimodalWindow(SimpleNamespace(core=None), main_surface=True)
    window._opened_once = True  # Render without starting a real engine/device.
    window.worker = SimpleNamespace(
        isRunning=lambda: True, gui_feeds_audio=True, audio_q=queue.Queue(),
        set_paused=lambda _: None, submit_image=lambda _: None,
    )
    monkeypatch.setattr(module, "_UNCLOSED_INPUT_STREAMS", [])
    yield window, app
    window.worker = None
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def permission(monkeypatch, status):
    app = SimpleNamespace(checkPermission=lambda _: status)
    monkeypatch.setattr(module, "QCoreApplication", SimpleNamespace(instance=lambda: app))
    return app


def sounddevice(monkeypatch, stream):
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        query_devices=lambda **_: {"name": "Test input"},
        InputStream=lambda **_: stream,
    ))


def test_preview_does_not_resize_window_or_panel_as_frames_arrive(face):
    window, app = face
    window.show()
    for _ in range(5):
        app.processEvents()
    initial_window = window.size()
    initial_preview = window.camera_label.size()
    for index in range(200):
        image = QImage(1280 if index % 2 else 720, 720, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        window._on_video_frame(SimpleNamespace(toImage=lambda: image))
        app.processEvents()
    assert window.size() == initial_window
    assert window.camera_label.size() == initial_preview
    assert window.camera_label.pixmap().width() <= window.camera_label.contentsRect().width()


def test_camera_waits_for_actual_audio_not_just_worker_ready(face, monkeypatch):
    window, _ = face
    permission(monkeypatch, Qt.PermissionStatus.Granted)
    monkeypatch.setattr(module, "QCamera", lambda *_: pytest.fail("camera before audio"))
    window._worker_ready = True
    window._open_selected_camera()
    assert "Waiting for microphone capture" in window.camera_label.text()
    assert window.camera is None


def test_muting_during_startup_does_not_race_engine_owned_device_initialization(face, monkeypatch):
    window, _ = face
    permission(monkeypatch, Qt.PermissionStatus.Granted)
    monkeypatch.setattr(module, "QCamera", lambda *_: pytest.fail("camera before audio initialization"))
    window._camera_devices = [SimpleNamespace(description=lambda: "Test camera")]
    window._mic_requested = False
    window._worker_ready = False
    window._open_selected_camera()
    assert window.camera is None
    assert "Waiting for audio pipeline initialization" in window.camera_label.text()


def test_microphone_first_packet_updates_level_and_resumes_camera(face, monkeypatch):
    window, _ = face
    resumed = []
    monkeypatch.setattr(window, "_resume_requested_camera", lambda: resumed.append(True))
    window._mic_device_name = "Test input"
    pcm = np.full((1600, 1), 0.1, dtype=np.float32)
    window._microphone_callback(pcm, 1600, None, None)
    assert not window._mic_capture_ready  # The GUI processes the bounded tap.
    window._paint_waveforms()
    assert window._mic_capture_ready
    assert window.mic_check.text() == "Mic: Live"
    assert window.mic_level.value() in (66, 67)
    assert "Test input" in window.mic_status.text()
    assert "1 blocks" in window.mic_status.text()
    assert resumed == [True]
    np.testing.assert_array_equal(window.worker.audio_q.get_nowait(), pcm[:, 0])
    window._microphone_callback(pcm, 1600, None, None)
    window._paint_waveforms()
    assert resumed == [True]


@pytest.mark.parametrize("mode", ["quasi", "full"])
def test_engine_owned_input_only_reports_live_after_mic_event(face, monkeypatch, mode):
    window, _ = face
    window.worker.gui_feeds_audio = False
    window.worker.audio_mode = mode
    monkeypatch.setattr(window, "_open_microphone", lambda: pytest.fail("second input stream"))
    window._on_ready()
    assert window.mic_check.text() == "Mic: Starting"
    assert not window._mic_capture_ready
    window._on_heard(np.zeros(1600, dtype=np.float32))
    window._paint_waveforms()
    assert window.mic_check.text() == "Mic: Live"
    assert "silent input" in window.mic_status.text()


def test_muted_ready_never_claims_an_active_aec_device(face, monkeypatch):
    window, _ = face
    paused = []
    window.worker.set_paused = paused.append
    window.mic_check.setChecked(False)
    monkeypatch.setattr(window, "_open_microphone", lambda: pytest.fail("muted input opened"))
    window._on_ready()
    assert window.mic_check.text() == "Mic: Muted"
    assert not window._mic_capture_ready
    assert paused == [True]


def test_stream_start_is_not_reported_as_capture(face, monkeypatch):
    window, _ = face
    calls = []
    permission(monkeypatch, Qt.PermissionStatus.Granted)
    stream = SimpleNamespace(start=lambda: calls.append("start"), stop=lambda **_: None, close=lambda **_: None)
    sounddevice(monkeypatch, stream)
    monkeypatch.setattr(window, "_close_camera", lambda: calls.append("camera closed"))
    window._open_microphone()
    assert calls == ["camera closed", "start"]
    assert window.mic_check.text() == "Mic: Starting"
    assert not window._mic_capture_ready
    window._mic_started_at = time.monotonic() - 6
    window._paint_waveforms()
    assert window.mic_check.text() == "Mic: No audio"
    assert window.mic_level.value() == 0


def test_failed_start_closes_stream_even_if_stop_also_raises(face, monkeypatch):
    window, _ = face
    calls = []
    permission(monkeypatch, Qt.PermissionStatus.Granted)

    def fail(**_):
        raise RuntimeError("PortAudio test error")

    def close(*, ignore_errors):
        assert ignore_errors is False
        calls.append("closed")

    sounddevice(monkeypatch, SimpleNamespace(start=fail, stop=fail, close=close))
    window._open_microphone()
    assert calls == ["closed"]
    assert window.mic_stream is None
    assert not window.mic_check.isChecked()
    assert not window._mic_requested
    assert window.mic_check.text() == "Mic: Error"
    assert "PortAudio test error" in window.mic_status.text()
    assert "retry" in window.mic_status.text()


def test_failed_native_close_retains_callback_owner(face):
    window, _ = face

    def fail(**_):
        raise RuntimeError("native close failed")

    stream = SimpleNamespace(stop=fail, close=fail)
    window.mic_stream = stream
    window._close_microphone()
    assert module._UNCLOSED_INPUT_STREAMS == [stream]
    assert window.mic_stream is None


def test_microphone_denial_is_actionable(face, monkeypatch):
    window, _ = face
    permission(monkeypatch, Qt.PermissionStatus.Denied)
    window._worker_ready = True
    window._open_microphone()
    assert not window.mic_check.isChecked()
    assert "Privacy & Security → Microphone" in window.mic_status.text()


@pytest.mark.parametrize("still_enabled", [False, True])
def test_microphone_permission_requested_once_and_honors_late_mute(face, monkeypatch, still_enabled):
    window, _ = face
    callbacks = []
    app = permission(monkeypatch, Qt.PermissionStatus.Undetermined)
    app.requestPermission = lambda permission, context, callback: callbacks.append(callback)
    window._worker_ready = True
    window._open_microphone()
    window._open_microphone()
    assert len(callbacks) == 1
    window._mic_requested = still_enabled
    opened = []
    monkeypatch.setattr(window, "_open_microphone", lambda: opened.append(True))
    callbacks[0](SimpleNamespace(status=lambda: Qt.PermissionStatus.Granted))
    assert opened == ([True] if still_enabled else [])


def test_stalled_capture_drops_live_indicator_and_recovers(face):
    window, _ = face
    window._mic_started_at = time.monotonic() - 10
    window._on_heard(np.zeros(1600, dtype=np.float32))
    window._paint_waveforms()
    assert window._mic_capture_ready
    window._mic_last_frame_at = time.monotonic() - 6
    window._paint_waveforms()
    assert not window._mic_capture_ready
    assert window.mic_check.text() == "Mic: No audio"
    window._on_heard(np.zeros(1600, dtype=np.float32))
    window._paint_waveforms()
    assert window.mic_check.text() == "Mic: Live"


def test_mute_rejects_late_audio_callbacks(face):
    window, _ = face
    window.mic_check.setChecked(False)
    pcm = np.full((1600, 1), 0.1, dtype=np.float32)
    window._microphone_callback(pcm, 1600, None, None)
    window._on_heard(pcm[:, 0])
    window._paint_waveforms()
    assert window._mic_blocks == 0
    assert window.worker.audio_q.empty()
    assert window.mic_check.text() == "Mic: Muted"


@pytest.mark.parametrize("event", ["ready", "failed", "heard"])
def test_queued_event_from_previous_worker_cannot_change_new_capture(face, monkeypatch, event):
    window, _ = face
    monkeypatch.setattr(window, "sender", lambda: object())
    monkeypatch.setattr(window, "_open_microphone", lambda: pytest.fail("old worker opened input"))
    original_status = window.status_label.text()
    if event == "ready":
        window._on_ready()
    elif event == "failed":
        window._on_failed("old worker failed")
    else:
        window._on_heard(np.zeros(1600, dtype=np.float32))
    assert not window._worker_ready
    assert window._mic_requested
    assert window._mic_blocks == 0
    assert window.status_label.text() == original_status
