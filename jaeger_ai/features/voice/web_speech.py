"""Recorded browser audio uses Jaeger's installed Whisper engine, without a device or second agent."""
from __future__ import annotations
import base64
import importlib.util
from pathlib import Path
import shutil
import tempfile
import threading

MAX_AUDIO_BYTES = 8 * 1024 * 1024
_MODEL = 'base.en'
_lock = threading.Lock()
_transcriber = None


def cached_model() -> Path | None:
    if importlib.util.find_spec('pywhispercpp') is None:
        return None
    from pywhispercpp.constants import MODELS_DIR
    path = Path(MODELS_DIR) / f'ggml-{_MODEL}.bin'
    return path if path.is_file() else None


def capability() -> dict:
    stt = (importlib.util.find_spec('jaeger_whisper_stt') is not None
           and cached_model() is not None and shutil.which('ffmpeg') is not None)
    tts = importlib.util.find_spec('jaeger_kokoro_tts') is not None
    return {'transcription': stt, 'speech': tts, 'provider': 'whisper_cpp', 'model': _MODEL,
            'microphone': 'client_permission_required', 'playback': 'client_device',
            'reason': '' if stt and tts else 'Install Jaeger speech packages, ffmpeg, and a cached Whisper base.en model.'}


def transcribe_recording(encoded: str, mime: str) -> str:
    global _transcriber
    suffix = {'audio/webm': '.webm', 'audio/ogg': '.ogg', 'audio/mp4': '.m4a', 'audio/wav': '.wav'}.get(mime.split(';')[0].strip().lower())
    if suffix is None:
        raise ValueError('Unsupported audio format')
    if not isinstance(encoded, str) or len(encoded) > (MAX_AUDIO_BYTES * 4 // 3 + 8):
        raise ValueError('Recording too large')
    try:
        audio = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError('Invalid audio recording') from exc
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError('Recording is empty or too large')
    model = cached_model()
    if model is None:
        raise RuntimeError('Whisper base.en is not cached; no model was downloaded')
    # The shared Whisper backend is not reentrant. Files are temporary and are
    # never indexed into session history or left in the repository.
    with _lock:
        if _transcriber is None:
            from jaeger_whisper_stt.offline import OfflineTranscriber
            _transcriber = OfflineTranscriber(str(model), language='en')
        with tempfile.TemporaryDirectory(prefix='jaeger-browser-speech-') as folder:
            path = Path(folder) / ('recording' + suffix)
            path.write_bytes(audio)
            return _transcriber.transcribe(path).text.strip()
