"""The droid's eyes: the Insta360 Link 2, a local vision model and a gimbal head.

* Frames come from the camera at a low working rate and never leave the Mac.
  Questions about what the droid sees go to the local VISION model
  (``qwen3-vl:8b-instruct`` through Ollama on this Mac).
* Presence is a cheap on-device face check every couple of seconds; it only
  says "someone is here" (no identification) and drives the welcome-back line.
* The head is the camera's gimbal, moved with standard UVC pan/tilt controls
  by the ``droid-ptz`` helper. Looking around = pan left, centre, right.

Freshness: an answer is only ever made from a frame captured in the last few
seconds; if the camera is stale the droid says so instead of guessing.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("JAEGER_VISION_MODEL", "qwen3-vl:8b-instruct")
PTZ = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger") / "droid/bin/droid-ptz"
FRESH_S = 3.0
STYLE = ("You are the eyes of Jaeger, a courteous household droid, looking through its own camera. "
         "Answer in one to three short spoken sentences, no lists or markdown. Describe only what is "
         "visible; say when you are unsure. Never identify people by name from their face.")


def camera_index(name: str) -> int:
    """OpenCV index of the camera called ``name`` (AVFoundation order), else 0."""
    try:
        import AVFoundation as A
        session = A.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
            [A.AVCaptureDeviceTypeExternal, A.AVCaptureDeviceTypeBuiltInWideAngleCamera,
             A.AVCaptureDeviceTypeContinuityCamera], A.AVMediaTypeVideo, 0)
        names = [d.localizedName() for d in session.devices()]
        for i, n in enumerate(names):
            if n == name:
                return i
    except Exception:
        pass
    return 0


def describe(jpeg: bytes | list[bytes], question: str, timeout: float = 60) -> str:
    images = [jpeg] if isinstance(jpeg, bytes) else jpeg
    body = {"model": MODEL, "stream": False, "think": False, "keep_alive": "30m",
            "options": {"num_ctx": 8192, "num_predict": 160, "temperature": 0.2},
            "messages": [{"role": "system", "content": STYLE},
                         {"role": "user", "content": question,
                          "images": [base64.b64encode(i).decode() for i in images]}]}
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return str((json.loads(resp.read()).get("message") or {}).get("content") or "").strip()


def warm():
    """Load the vision model into memory without an image (keeps first look fast)."""
    # Same num_ctx as describe(), or Ollama reloads the model on the first real look.
    body = {"model": MODEL, "keep_alive": "30m", "prompt": "", "stream": False, "options": {"num_ctx": 8192}}
    try:
        urllib.request.urlopen(urllib.request.Request(
            OLLAMA + "/api/generate", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}), timeout=120).read()
    except Exception:
        pass


def is_warm() -> bool:
    """True when the vision model is already loaded in Ollama."""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=2) as resp:
            return any(m.get("name") == MODEL for m in json.loads(resp.read()).get("models") or [])
    except Exception:
        return False


class Head:
    """Gimbal pan/tilt in UVC units (arc-seconds; 3600 = one degree)."""

    def __init__(self):
        self.info: dict = {}

    def _run(self, *args) -> dict:
        if not PTZ.exists():
            return {}
        try:
            out = subprocess.run([str(PTZ), *map(str, args)], capture_output=True, text=True, timeout=5)
            self.info = json.loads(out.stdout or "{}")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.info = {}
        return self.info

    def where(self) -> tuple[int, int] | None:
        cur = self._run("info").get("pantilt_cur")
        return (int(cur["pan"]), int(cur["tilt"])) if cur else None

    def point(self, pan_deg: float, tilt_deg: float) -> bool:
        info = self.info or self._run("info")
        lo, hi = info.get("pantilt_min") or {}, info.get("pantilt_max") or {}
        pan = int(round(pan_deg)) * 3600
        tilt = int(round(tilt_deg)) * 3600
        if lo and hi:
            pan = max(lo["pan"], min(hi["pan"], pan))
            tilt = max(lo["tilt"], min(hi["tilt"], tilt))
        return bool(self._run("abs", pan, tilt).get("ok"))

    def nudge(self, pan_deg: float = 0, tilt_deg: float = 0) -> bool:
        cur = self.where()
        if cur is None:
            return False
        return self.point(cur[0] / 3600 + pan_deg, cur[1] / 3600 + tilt_deg)


class Eyes:
    def __init__(self, camera: str, on_presence=None, report=None):
        self.camera = camera
        self.on_presence = on_presence or (lambda arrived, faces: None)
        self.report = report or (lambda **f: None)
        self.head = Head()
        self.frame = None
        self.frame_at = 0.0
        self.faces = 0
        self.present = False
        self.last_seen = 0.0
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.error: str | None = None

    def start(self):
        self.stopped.clear()
        self.thread = threading.Thread(target=self._run, name="droid-eyes", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _run(self):
        import cv2

        cap = cv2.VideoCapture(camera_index(self.camera), cv2.CAP_AVFOUNDATION)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        if not cap.isOpened():
            self.error = "The camera would not open (permission or device in use)"
            self.report(camera="error", camera_error=self.error)
            return
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.report(camera="live", camera_error=None)
        next_presence = 0.0
        absent_since = time.time()
        try:
            while not self.stopped.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.2)
                    continue
                now = time.time()
                with self.lock:
                    self.frame, self.frame_at = frame, now
                if now >= next_presence:
                    next_presence = now + 1.5
                    gray = cv2.cvtColor(cv2.resize(frame, (640, 360)), cv2.COLOR_BGR2GRAY)
                    faces = cascade.detectMultiScale(gray, 1.15, 6, minSize=(36, 36))
                    self.faces = len(faces)
                    if self.faces:
                        if not self.present:
                            away = now - absent_since
                            self.present = True
                            self.on_presence(away, self.faces)
                        self.last_seen = now
                    elif self.present and now - self.last_seen > 20:
                        self.present = False
                        absent_since = self.last_seen
                    self.report(faces=self.faces, present=self.present)
                time.sleep(0.03)
        finally:
            cap.release()
            self.report(camera="off")

    def jpeg(self, width: int = 1024, max_age: float = FRESH_S) -> bytes | None:
        import cv2

        with self.lock:
            frame, at = self.frame, self.frame_at
        if frame is None or time.time() - at > max_age:
            return None
        h, w = frame.shape[:2]
        if w > width:
            frame = cv2.resize(frame, (width, int(h * width / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        return buf.tobytes() if ok else None

    def wait_fresh(self, timeout: float = 4.0) -> bytes | None:
        start = time.time()
        while time.time() - start < timeout:
            img = self.jpeg()
            if img and self.frame_at >= start:
                return img
            time.sleep(0.05)
        return self.jpeg()

    def look(self, question: str) -> str:
        img = self.wait_fresh()
        if img is None:
            return "I'm afraid my camera isn't giving me a fresh picture just now."
        return describe(img, question)

    def look_around(self, question: str) -> str:
        """Pan left, centre and right; describe the three views together."""
        start = self.head.where()
        views = []
        for pan in (-60, 0, 60):
            if self.head.point(pan, 0):
                time.sleep(1.6)
            img = self.wait_fresh(3)
            if img:
                views.append(img)
        if start:
            self.head.point(start[0] / 3600, start[1] / 3600)
        if not views:
            return "I'm afraid my camera isn't giving me a fresh picture just now."
        return describe(views, question + " (These are three views: left, centre and right of the room.)")
