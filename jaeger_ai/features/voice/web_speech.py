"""Recorded browser audio uses Jaeger's installed Whisper engine, without a device or second agent."""
from __future__ import annotations
import base64
import importlib.util
from pathlib import Path
import shutil
import tempfile
import threading

MAX_AUDIO_BYTES = 8 * 1024 * 1024
# Most accurate cached model first. large-v3-turbo decodes a short utterance in
# ~0.7 s warm on the M1 Max (base.en: 0.1 s, but heard "Jaeger" as "Hater").
_MODELS = ('large-v3-turbo', 'medium.en', 'base.en')
_lock = threading.Lock()
_transcriber = None


def _cached() -> tuple[str, Path] | None:
    if importlib.util.find_spec('pywhispercpp') is None:
        return None
    from pywhispercpp.constants import MODELS_DIR
    for name in _MODELS:
        path = Path(MODELS_DIR) / f'ggml-{name}.bin'
        if path.is_file():
            return name, path
    return None


def cached_model() -> Path | None:
    found = _cached()
    return found[1] if found else None


def _model_name() -> str:
    found = _cached()
    return found[0] if found else _MODELS[-1]


def _load():
    global _transcriber
    if _transcriber is None:
        from jaeger_whisper_stt.offline import OfflineTranscriber
        _transcriber = OfflineTranscriber(str(cached_model()), language='en')
    return _transcriber


def warm() -> None:
    """Preload Whisper and the voice brain (Kokoro warms at WebUI start) in the background when voice mode opens."""
    def run():
        try:
            if cached_model() is not None:
                with _lock:
                    _load()
        except Exception:  # noqa: BLE001 — warming is an optimisation only
            pass
    try:
        from jaeger_ai.features.voice.brain import warm as warm_brain
        warm_brain()
    except Exception:  # noqa: BLE001
        pass
    threading.Thread(target=run, name='voice-warm', daemon=True).start()


def capability() -> dict:
    stt = (importlib.util.find_spec('jaeger_whisper_stt') is not None
           and cached_model() is not None and shutil.which('ffmpeg') is not None)
    tts = importlib.util.find_spec('jaeger_kokoro_tts') is not None
    return {'transcription': stt, 'speech': tts, 'provider': 'whisper_cpp', 'model': _model_name(),
            'microphone': 'client_permission_required', 'playback': 'client_device',
            'reason': '' if stt and tts else 'Install Jaeger speech packages, ffmpeg, and a cached Whisper model.'}


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
        raise RuntimeError('No Whisper model is cached; no model was downloaded')
    # The shared Whisper backend is not reentrant. Files are temporary and are
    # never indexed into session history or left in the repository.
    with _lock:
        transcriber = _load()
        with tempfile.TemporaryDirectory(prefix='jaeger-browser-speech-') as folder:
            path = Path(folder) / ('recording' + suffix)
            path.write_bytes(audio)
            return transcriber.transcribe(path).text.strip()
