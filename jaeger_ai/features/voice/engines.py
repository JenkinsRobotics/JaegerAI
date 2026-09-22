"""What voice can actually use on this machine, and how to build it.

Engines come from the application's module slots: ``stt`` (filled by
jaeger-whisper-stt) and ``tts`` (filled by jaeger-kokoro-tts). This file
never picks a model for the *mind*; cognition belongs to the Entity.

Every status here is measured, not assumed: a package that imports is
SUPPORTED; weights on disk make it CONFIGURED; an input device the OS
reports makes the microphone AVAILABLE. Microphone permission is TCC's to
grant and is only known once capture actually starts.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
from typing import Any

#: Whisper weights pywhispercpp downloads on first use.
WHISPER_MODEL_DIR = Path.home() / "Library" / "Application Support" / "pywhispercpp" / "models"
#: Kokoro weights in the Hugging Face cache.
KOKORO_CACHE = Path.home() / ".cache" / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M"


@dataclass(frozen=True)
class EngineStatus:
    name: str
    supported: bool
    configured: bool
    available: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "supported": self.supported, "configured": self.configured,
            "available": self.available, "detail": self.detail,
        }


def _importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def stt_status(model_name: str = "base.en") -> EngineStatus:
    supported = _importable("jaeger_whisper_stt") and _importable("pywhispercpp")
    weights = WHISPER_MODEL_DIR / f"ggml-{model_name}.bin"
    configured = supported and weights.is_file()
    detail = str(weights) if configured else f"missing {weights}" if supported else "jaeger-whisper-stt / pywhispercpp not installed"
    return EngineStatus("whisper.cpp", supported, configured, configured, detail)


def tts_status() -> EngineStatus:
    supported = _importable("jaeger_kokoro_tts") and _importable("kokoro")
    configured = supported and KOKORO_CACHE.is_dir()
    output = _default_device("output") if configured else None
    available = configured and output is not None
    if not supported:
        detail = "jaeger-kokoro-tts / kokoro not installed"
    elif not configured:
        detail = f"missing {KOKORO_CACHE}"
    else:
        detail = f"output device: {output}" if output else "no output device"
    return EngineStatus("kokoro-82M", supported, configured, available, detail)


def microphone_status() -> EngineStatus:
    supported = _importable("sounddevice")
    device = _default_device("input") if supported else None
    detail = f"input device: {device} (TCC permission is checked when capture starts)" if device else "no input device"
    return EngineStatus("microphone", supported, device is not None, device is not None, detail)


def _default_device(kind: str) -> str | None:
    try:
        import sounddevice as sd

        info = sd.query_devices(kind=kind)
        return str(info.get("name")) if info else None
    except Exception:  # noqa: BLE001 — no PortAudio / no device is an answer, not a crash
        return None


def voice_status() -> dict[str, Any]:
    """Machine-readable voice capability truth."""
    stt, tts, mic = stt_status(), tts_status(), microphone_status()
    return {
        "stt": stt.as_dict(),
        "tts": tts.as_dict(),
        "microphone": mic.as_dict(),
        "spoken_input": stt.available and mic.available,
        "spoken_output": tts.available,
    }


def make_microphone_listener(model_name: str = "base.en", **kwargs: Any) -> Any:
    """The stt slot's continuous Whisper engine on the default microphone."""
    from jaeger_whisper_stt.nodes.whisper_stt.engine import WhisperSTTContinuous

    return WhisperSTTContinuous(model_name=model_name, **kwargs)


def make_kokoro_speaker(**kwargs: Any) -> Any:
    """The tts slot's Kokoro engine on the default output device."""
    from jaeger_kokoro_tts.nodes.kokoro_tts.engine import KokoroTTS

    return KokoroTTS(**kwargs)
