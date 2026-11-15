"""The droid's local senses: who is in the room, are they facing it, is anyone talking.

Everything here runs on the Mac and keeps nothing but numbers:

* ``detect`` — Apple Vision person + face rectangles with head direction
  (yaw / pitch) on one small frame (Neural Engine / CPU, a few ms).
* ``FaceID`` — OpenCV YuNet + SFace face embeddings (ONNX, local). Only the
  owner's averaged 128-d vector is stored, in ``~/.jaeger/droid/identity``.
* ``VoiceID`` — WeSpeaker ResNet34 speaker embeddings (ONNX, local) from
  80-bin log-mel features. Only the owner's averaged 256-d vector is stored.
* ``Ears`` — Silero VAD on the microphone: a speech yes/no, no recording and
  no transcription.

No frame, image or audio is written to disk or sent anywhere by this module.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path

import numpy as np

STATE = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")
MODELS = STATE / "droid" / "models"
IDENTITY = STATE / "droid" / "identity"
FACE_MATCH = 0.40    # SFace cosine; OpenCV's published same-person threshold is 0.363
VOICE_MATCH = 0.55   # WeSpeaker cosine on short utterances


# ── Apple Vision ──────────────────────────────────────────────────────
def detect(jpeg: bytes) -> dict:
    """People and faces in one JPEG frame (normalized boxes, top-left origin).

    Returns ``{"people": [{"box"}], "faces": [{"box", "yaw", "pitch", "facing"}]}``;
    ``facing`` is true when the head points within ~25° of the camera.
    """
    import Foundation
    import Vision

    data = Foundation.NSData.dataWithBytes_length_(jpeg, len(jpeg))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    faces = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    try:
        faces.setRevision_(Vision.VNDetectFaceRectanglesRequestRevision3)
    except Exception:  # older macOS: revision 2 still has yaw
        pass
    people = Vision.VNDetectHumanRectanglesRequest.alloc().init()
    try:
        people.setUpperBodyOnly_(False)
    except Exception:
        pass
    handler.performRequests_error_([faces, people], None)

    def box(obs):
        b = obs.boundingBox()
        x, y, w, h = b.origin.x, b.origin.y, b.size.width, b.size.height
        return [round(x, 4), round(1 - y - h, 4), round(w, 4), round(h, 4)]

    def angle(value):
        if value is None:
            return None
        try:
            return round(math.degrees(float(value)), 1)
        except (TypeError, ValueError):
            return None

    out_faces = []
    for obs in faces.results() or []:
        yaw = angle(obs.yaw()) if hasattr(obs, "yaw") else None
        pitch = angle(obs.pitch()) if hasattr(obs, "pitch") else None
        out_faces.append({"box": box(obs), "yaw": yaw, "pitch": pitch,
                          "facing": yaw is not None and abs(yaw) <= 25 and (pitch is None or abs(pitch) <= 30)})
    out_people = [{"box": box(obs)} for obs in people.results() or []]
    return {"people": out_people, "faces": out_faces}


# ── identity store ────────────────────────────────────────────────────
def _vector_path(kind: str) -> Path:
    return IDENTITY / f"{kind}.npy"


def enrolled() -> dict:
    meta = {}
    try:
        meta = json.loads((IDENTITY / "enrolled.json").read_text())
    except (OSError, ValueError):
        pass
    return {kind: {"enrolled": _vector_path(kind).exists(), **(meta.get(kind) or {})} for kind in ("face", "voice")}


def save_vector(kind: str, vectors: list[np.ndarray], samples: int):
    IDENTITY.mkdir(parents=True, exist_ok=True, mode=0o700)
    mean = np.mean(np.stack(vectors), axis=0)
    mean = mean / (np.linalg.norm(mean) or 1.0)
    np.save(_vector_path(kind), mean.astype(np.float32))
    _vector_path(kind).chmod(0o600)
    meta_path = IDENTITY / "enrolled.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        meta = {}
    meta[kind] = {"at": time.time(), "samples": samples}
    meta_path.write_text(json.dumps(meta))
    meta_path.chmod(0o600)


def load_vector(kind: str) -> np.ndarray | None:
    try:
        return np.load(_vector_path(kind))
    except (OSError, ValueError):
        return None


def forget(kind: str) -> bool:
    """Delete an enrolled vector (the owner asked; nothing else is kept)."""
    path = _vector_path(kind)
    existed = path.exists()
    path.unlink(missing_ok=True)
    meta_path = IDENTITY / "enrolled.json"
    try:
        meta = json.loads(meta_path.read_text())
        meta.pop(kind, None)
        meta_path.write_text(json.dumps(meta))
    except (OSError, ValueError):
        pass
    return existed


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))


# ── faces ─────────────────────────────────────────────────────────────
class FaceID:
    def __init__(self):
        import cv2

        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(MODELS / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.8)
        self.recognizer = cv2.FaceRecognizerSF.create(str(MODELS / "face_recognition_sface_2021dec.onnx"), "")
        self.owner = load_vector("face")
        self.lock = threading.Lock()

    def embeddings(self, bgr: np.ndarray) -> list[tuple[list[float], np.ndarray]]:
        """(box, 128-d feature) for each face in a BGR frame."""
        h, w = bgr.shape[:2]
        with self.lock:
            self.detector.setInputSize((w, h))
            _, faces = self.detector.detect(bgr)
            out = []
            for face in faces if faces is not None else []:
                crop = self.recognizer.alignCrop(bgr, face)
                feat = self.recognizer.feature(crop).flatten()
                x, y, fw, fh = face[:4]
                out.append(([x / w, y / h, fw / w, fh / h], feat))
        return out

    def owner_score(self, bgr: np.ndarray) -> tuple[float | None, int]:
        """Best cosine against the enrolled owner and the number of faces seen."""
        found = self.embeddings(bgr)
        if self.owner is None or not found:
            return None, len(found)
        return max(_cos(self.owner, feat) for _, feat in found), len(found)

    def reload(self):
        self.owner = load_vector("face")


# ── voices ────────────────────────────────────────────────────────────
def _mel_bank(sr=16000, n_fft=512, n_mels=80, fmin=20.0, fmax=7600.0) -> np.ndarray:
    def mel(f):
        return 1127.0 * np.log(1.0 + f / 700.0)

    def hz(m):
        return 700.0 * (np.exp(m / 1127.0) - 1.0)

    points = hz(np.linspace(mel(fmin), mel(fmax), n_mels + 2))
    bins = np.fft.rfftfreq(n_fft, 1.0 / sr)
    bank = np.zeros((n_mels, bins.size), np.float32)
    for i in range(n_mels):
        lo, mid, hi = points[i], points[i + 1], points[i + 2]
        bank[i] = np.clip(np.minimum((bins - lo) / (mid - lo), (hi - bins) / (hi - mid)), 0, None)
    return bank


_BANK = None


def fbank(pcm16k: np.ndarray) -> np.ndarray:
    """Kaldi-style 80-bin log-mel features (25 ms / 10 ms, povey window), mean-normalized."""
    global _BANK
    if _BANK is None:
        _BANK = _mel_bank()
    x = pcm16k.astype(np.float32) * 32768.0
    frame, hop = 400, 160
    if x.size < frame:
        x = np.pad(x, (0, frame - x.size))
    n = 1 + (x.size - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1], frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    window = np.power(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(frame) / (frame - 1)), 0.85)
    power = np.abs(np.fft.rfft(frames * window, 512)) ** 2
    feats = np.log(np.maximum(power @ _BANK.T, 1.1920929e-07))
    return (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)


class VoiceID:
    def __init__(self):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(MODELS / "wespeaker_resnet34.onnx"), opts,
                                            providers=["CPUExecutionProvider"])
        self.owner = load_vector("voice")

    def embed(self, pcm16k: np.ndarray) -> np.ndarray:
        feats = fbank(pcm16k)[None]
        return self.session.run(["embs"], {"feats": feats})[0][0]

    def owner_score(self, pcm16k: np.ndarray) -> float | None:
        if self.owner is None or pcm16k.size < 16000:  # under a second says too little
            return None
        return _cos(self.owner, self.embed(pcm16k))

    def reload(self):
        self.owner = load_vector("voice")


# ── ears (VAD only) ───────────────────────────────────────────────────
class Ears:
    """Speech yes/no from 48 kHz microphone blocks. Keeps ~8 s of 16 kHz audio in
    memory only while someone is speaking, for the voice match, then drops it."""

    def __init__(self):
        from pipecat.audio.vad.silero import SileroVADAnalyzer

        self.vad = SileroVADAnalyzer(sample_rate=16000)
        self.vad.set_sample_rate(16000)
        self.need = self.vad.num_frames_required()
        self.pending = np.zeros(0, np.int16)
        self.speaking = False
        self.speech_started = 0.0
        self.last_voice = 0.0
        self.utterance: list[np.ndarray] = []
        self.clock = 0.0   # audio time in seconds (works faster than real time in tests)

    def feed(self, block48k: np.ndarray) -> tuple[str | None, np.ndarray | None]:
        """Returns ("start"|"end"|None, finished utterance at 16 kHz or None)."""
        pcm = block48k.astype(np.float32)
        usable = pcm.size - pcm.size % 3
        down = pcm[:usable].reshape(-1, 3).mean(axis=1).astype(np.int16)
        self.pending = np.concatenate([self.pending, down])
        event, done = None, None
        while self.pending.size >= self.need:
            chunk, self.pending = self.pending[:self.need], self.pending[self.need:]
            self.clock += self.need / 16000
            now = self.clock
            voiced = self.vad.voice_confidence(chunk.tobytes()) >= 0.6
            if voiced:
                self.last_voice = now
                if not self.speaking:
                    self.speaking, self.speech_started, event = True, now, "start"
                    self.utterance = []
            if self.speaking:
                self.utterance.append(chunk)
                if sum(c.size for c in self.utterance) > 16000 * 8:
                    self.utterance.pop(0)
                if now - self.last_voice > 0.8:
                    self.speaking, event = False, "end"
                    done = np.concatenate(self.utterance).astype(np.float32) / 32768.0
                    self.utterance = []
        return event, done
