"""Live GUI/device regression probe; no model, transcription, or saved media.

Run with the desktop bundle's JaegerMultimodal interpreter and its configured
PYTHONHOME/site-packages so macOS uses the application's privacy identity:
    JaegerMultimodal dev/verification/multimodal_capture.py <venv-site-packages>

The probe displays actual camera frames and measures live microphone PCM.
Only counts, levels, geometry, and pass/fail results are printed as JSON.
Close other multimodal faces first to avoid competing for capture devices.
"""

from __future__ import annotations

import json
import queue
import site
import sys
import time
from types import SimpleNamespace


def main() -> int:
    if len(sys.argv) > 1:
        site.addsitedir(sys.argv[1])

    import numpy as np
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from jaeger_ai.interfaces.pyside6.multimodal.window import MultimodalWindow

    app = QApplication.instance() or QApplication([])
    face = MultimodalWindow(SimpleNamespace(core=None), main_surface=True)
    face._opened_once = True  # Drive the real device lifecycle without an LLM.
    face.worker = SimpleNamespace(
        isRunning=lambda: True, gui_feeds_audio=True, audio_q=queue.Queue(),
        set_paused=lambda _: None, submit_image=lambda _: None,
    )
    totals = {"audio_blocks": 0, "video_frames": 0, "peak": 0.0}
    audio_before_first_video = []
    original_audio = face._microphone_callback
    original_video = face._on_video_frame

    def audio(data, frames, timestamp, status):
        totals["audio_blocks"] += 1
        totals["peak"] = max(totals["peak"], float(np.max(np.abs(data))))
        original_audio(data, frames, timestamp, status)

    def video(frame):
        if not frame.toImage().isNull():
            if not totals["video_frames"]:
                audio_before_first_video.append(totals["audio_blocks"])
            totals["video_frames"] += 1
        original_video(frame)

    face._microphone_callback = audio
    face._on_video_frame = video
    phases = []

    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            # The stub consumes PCM without retaining it or running inference.
            while not face.worker.audio_q.empty():
                face.worker.audio_q.get_nowait()
            time.sleep(0.01)

    def measure(name):
        # Allow camera/permission/device transitions and layout to settle.
        pump(2)
        before = dict(totals)
        geometry = (face.width(), face.height(), face.camera_label.width(), face.camera_label.height())
        pump(6)
        after = (face.width(), face.height(), face.camera_label.width(), face.camera_label.height())
        phases.append({
            "phase": name,
            "audio_blocks": totals["audio_blocks"] - before["audio_blocks"],
            "video_frames": totals["video_frames"] - before["video_frames"],
            "geometry": after,
            "geometry_stable": geometry == after,
            "mic_status": face.mic_status.text(),
            "mic_live": face._mic_capture_ready,
            "camera_active": bool(face.camera and face.camera.isActive()),
        })

    try:
        face.show()
        face.video_check.setChecked(True)  # Must wait even if video is requested first.
        face._on_ready()
        measure("initial audio-first capture")
        face.mic_check.setChecked(False)
        pump(1)
        muted_at = totals["audio_blocks"]
        pump(1)
        muted_quiet = muted_at == totals["audio_blocks"]
        face.mic_check.setChecked(True)
        measure("unmute with camera previously active")
        face.video_check.setChecked(False)
        pump(1)
        face.video_check.setChecked(True)
        measure("camera off/on with microphone active")
        face._close_camera()
        face._close_microphone()
        face._on_ready()
        measure("audio resource restart")
        passed = bool(audio_before_first_video and audio_before_first_video[0] > 0)
        passed = passed and muted_quiet and all(
            p["audio_blocks"] > 0 and p["video_frames"] > 0
            and p["geometry_stable"] and p["mic_live"] and p["camera_active"]
            for p in phases
        )
        result = {
            "passed": passed, "audio_before_first_video": audio_before_first_video,
            "mute_stopped_callbacks": muted_quiet, "totals": totals, "phases": phases,
            "models_loaded": False, "media_saved": False,
        }
    finally:
        face.worker = None
        face.close()
        face.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
