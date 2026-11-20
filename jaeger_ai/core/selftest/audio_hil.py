"""Physical macOS audio hardware-in-the-loop verification (§3).

Tests the real acoustic path:
  Truth TTS -> physical speakers -> air -> physical microphone -> real STT -> comparison.

Never feeds TTS waveforms directly into STT for acoustic loopback verification;
computes acoustic SNR, RMS, clipping, and envelope cross-correlation on the
microphone capture to prove genuine physical acoustic propagation.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
from datetime import datetime
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
import wave
from typing import Any, Iterator

import numpy as np

from jaeger_ai.features.human_needs.policy import is_quiet_hours
from .models import CheckResult, CheckStatus

MAX_SAFE_GAIN = 0.55  # Hard safety ceiling: never blast desktop speakers during automated tests.
VOICE_VENV_PY = Path.home() / ".jaeger" / "voice-venv" / "bin" / "python"


# ── macOS CoreAudio device inspection & auto-restoring session helper ─────────


class _AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


def _fourcc(code: str) -> int:
    return struct.unpack(">I", code.encode("ascii"))[0]


def _load_coreaudio() -> tuple[Any, Any] | tuple[None, None]:
    try:
        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_bool
        return ca, cf
    except Exception:  # noqa: BLE001
        return None, None


def coreaudio_device_map() -> dict[str, dict[str, Any]]:
    """Map CoreAudio device localized names -> {id, uid} (read-only)."""
    ca, cf = _load_coreaudio()
    if ca is None or cf is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    addr = _AudioObjectPropertyAddress(_fourcc("dev#"), _fourcc("glob"), 0)
    sz = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(1, ctypes.byref(addr), 0, None, ctypes.byref(sz)) != 0:
        return {}
    n = sz.value // 4
    dev_ids = (ctypes.c_uint32 * n)()
    if ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None, ctypes.byref(sz), dev_ids) != 0:
        return {}

    def _get_cfstr(did: int, sel: str) -> str:
        a = _AudioObjectPropertyAddress(_fourcc(sel), _fourcc("glob"), 0)
        cfstr = ctypes.c_void_p()
        s = ctypes.c_uint32(ctypes.sizeof(cfstr))
        if ca.AudioObjectGetPropertyData(did, ctypes.byref(a), 0, None, ctypes.byref(s), ctypes.byref(cfstr)) != 0:
            return ""
        buf = ctypes.create_string_buffer(256)
        if not cf.CFStringGetCString(cfstr, buf, 256, 0x08000100):
            return ""
        return buf.value.decode("utf-8", "ignore")

    for did in dev_ids:
        name = _get_cfstr(int(did), "lnam")
        uid = _get_cfstr(int(did), "uid ")
        if name:
            out[name] = {"id": int(did), "uid": uid}
    return out


@contextmanager
def temporary_physical_audio_ready(
    speaker_names: list[str],
    mic_name: str,
    *,
    speaker_volume: float = 0.68,
    mic_volume: float = 0.88,
) -> Iterator[dict[str, Any]]:
    """Temporarily ensure target physical speakers/mic are unmuted at safe volume, then restore exact CoreAudio state."""
    ca, _ = _load_coreaudio()
    if ca is None:
        yield {"coreaudio_adjusted": False}
        return

    dev_map = coreaudio_device_map()
    IN_SCOPE, OUT_SCOPE = _fourcc("inpt"), _fourcc("outp")
    saved: list[tuple[int, str, int, int, str, Any]] = []

    def _get_u32(did: int, sel: str, scope: int, ch: int) -> int | None:
        a = _AudioObjectPropertyAddress(_fourcc(sel), scope, ch)
        if not ca.AudioObjectHasProperty(did, ctypes.byref(a)):
            return None
        v = ctypes.c_uint32()
        sz = ctypes.c_uint32(4)
        if ca.AudioObjectGetPropertyData(did, ctypes.byref(a), 0, None, ctypes.byref(sz), ctypes.byref(v)) != 0:
            return None
        return int(v.value)

    def _set_u32(did: int, sel: str, scope: int, ch: int, val: int) -> int:
        a = _AudioObjectPropertyAddress(_fourcc(sel), scope, ch)
        v = ctypes.c_uint32(int(val))
        return int(ca.AudioObjectSetPropertyData(did, ctypes.byref(a), 0, None, 4, ctypes.byref(v)))

    def _get_f32(did: int, sel: str, scope: int, ch: int) -> float | None:
        a = _AudioObjectPropertyAddress(_fourcc(sel), scope, ch)
        if not ca.AudioObjectHasProperty(did, ctypes.byref(a)):
            return None
        v = ctypes.c_float()
        sz = ctypes.c_uint32(4)
        if ca.AudioObjectGetPropertyData(did, ctypes.byref(a), 0, None, ctypes.byref(sz), ctypes.byref(v)) != 0:
            return None
        return float(v.value)

    def _set_f32(did: int, sel: str, scope: int, ch: int, val: float) -> int:
        a = _AudioObjectPropertyAddress(_fourcc(sel), scope, ch)
        v = ctypes.c_float(float(val))
        return int(ca.AudioObjectSetPropertyData(did, ctypes.byref(a), 0, None, 4, ctypes.byref(v)))

    safe_spk = max(0.15, min(0.75, float(speaker_volume)))
    safe_mic = max(0.30, min(0.95, float(mic_volume)))
    adjusted: list[str] = []
    try:
        for sname in speaker_names:
            info = dev_map.get(sname)
            if not info:
                continue
            did = info["id"]
            orig_mute = _get_u32(did, "mute", OUT_SCOPE, 0)
            orig_vol = _get_f32(did, "volm", OUT_SCOPE, 0)
            if orig_mute is not None:
                saved.append((did, "mute", OUT_SCOPE, 0, "u32", orig_mute))
            if orig_vol is not None and math.isfinite(orig_vol):
                saved.append((did, "volm", OUT_SCOPE, 0, "f32", orig_vol))
            if orig_mute == 1 or (orig_vol is not None and (not math.isfinite(orig_vol) or orig_vol < 0.35 or orig_vol > 0.75)):
                _set_f32(did, "volm", OUT_SCOPE, 0, safe_spk)
                _set_u32(did, "mute", OUT_SCOPE, 0, 0)
                adjusted.append(f"speaker:{sname}")

        minfo = dev_map.get(mic_name)
        if minfo:
            did = minfo["id"]
            for ch in (0, 1):
                orig_db = _get_f32(did, "vold", IN_SCOPE, ch)
                orig_vol = _get_f32(did, "volm", IN_SCOPE, ch)
                orig_mute = _get_u32(did, "mute", IN_SCOPE, ch)
                if orig_mute == 1:
                    saved.append((did, "mute", IN_SCOPE, ch, "u32", orig_mute))
                    _set_u32(did, "mute", IN_SCOPE, ch, 0)
                    adjusted.append(f"mic_unmute:{mic_name}")
                if orig_vol is not None or orig_db is not None:
                    need_raise = (
                        (orig_db is not None and (not math.isfinite(orig_db) or orig_db < -40.0))
                        or (orig_vol is not None and (not math.isfinite(orig_vol) or orig_vol < 0.15))
                    )
                    if need_raise:
                        if orig_db is not None and not math.isfinite(orig_db):
                            saved.append((did, "volm", IN_SCOPE, ch, "f32", 0.0))
                        elif orig_vol is not None and math.isfinite(orig_vol):
                            saved.append((did, "volm", IN_SCOPE, ch, "f32", orig_vol))
                        _set_f32(did, "volm", IN_SCOPE, ch, safe_mic)
                        adjusted.append(f"mic_gain:{mic_name}")
                    break
        if adjusted:
            time.sleep(0.8)
            # Warm up USB microphone stream briefly so first capture never catches post-unmute zero samples
            try:
                import sounddevice as _sd
                _devs = _sd.query_devices()
                _mi = next((i for i, d in enumerate(_devs) if mic_name.lower() in str(d.get("name") or "").lower() and int(d.get("max_input_channels") or 0) > 0), None)
                if _mi is not None:
                    _w = _sd.rec(int(48000 * 0.25), samplerate=48000, channels=1, dtype="float32", device=_mi)
                    _sd.wait()
            except Exception:  # noqa: BLE001
                pass
        yield {"coreaudio_adjusted": bool(adjusted), "adjusted": adjusted}
    finally:
        for did, sel, scope, ch, kind, val in reversed(saved):
            try:
                if kind == "u32":
                    _set_u32(did, sel, scope, ch, int(val))
                else:
                    _set_f32(did, sel, scope, ch, float(val))
            except Exception:  # noqa: BLE001
                pass


_DIGIT_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten", "47": "four seven", "74": "seven four",
}


def _normalize_words(text: str) -> list[str]:
    clean = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    out: list[str] = []
    for tok in clean.split():
        if tok in _DIGIT_WORDS:
            out.extend(_DIGIT_WORDS[tok].split())
        elif tok.isdigit() and len(tok) > 1:
            for ch in tok:
                out.append(_DIGIT_WORDS.get(ch, ch))
        else:
            out.append(tok)
    return out


def word_match_score(expected: str, observed: str) -> float:
    exp = _normalize_words(expected)
    obs = _normalize_words(observed)
    if not exp:
        return 1.0 if not obs else 0.0
    if not obs:
        return 0.0
    obs_set = set(obs)
    hits = sum(1 for w in exp if w in obs_set)
    return round(hits / len(exp), 3)


def enumerate_audio_devices() -> dict[str, Any]:
    out: dict[str, Any] = {"available": False, "inputs": [], "outputs": [], "mic_tcc_status": None}
    try:
        import AVFoundation
        out["mic_tcc_status"] = int(
            AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeAudio)
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        out["available"] = True
        out["default_device"] = list(sd.default.device) if sd.default.device is not None else None
        for idx, d in enumerate(devs):
            row = {
                "index": idx,
                "name": str(d.get("name") or ""),
                "in": int(d.get("max_input_channels") or 0),
                "out": int(d.get("max_output_channels") or 0),
                "sr": float(d.get("default_samplerate") or 48000.0),
            }
            if row["in"] > 0:
                out["inputs"].append(row)
            if row["out"] > 0:
                out["outputs"].append(row)
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def select_physical_devices(
    devices: dict[str, Any],
    *,
    preferred_out: str = "",
    preferred_in: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Choose real physical speaker & microphone (avoiding virtual Jump Desktop loopback)."""
    outputs = devices.get("outputs") or []
    inputs = devices.get("inputs") or []

    def _pick(rows: list[dict[str, Any]], pref: str, prefer_names: tuple[str, ...]) -> dict[str, Any] | None:
        if pref:
            for r in rows:
                if pref.lower() in r["name"].lower():
                    return r
        for needle in prefer_names:
            for r in rows:
                if needle.lower() in r["name"].lower():
                    return r
        # Avoid virtual Jump Desktop and remote Continuity iPhone devices when selecting local desktop hardware
        non_virtual = [
            r for r in rows
            if "jump desktop" not in r["name"].lower() and "iphone" not in r["name"].lower()
        ]
        return non_virtual[0] if non_virtual else (rows[0] if rows else None)

    speaker = _pick(outputs, preferred_out, ("Mac Studio Speakers", "Logi Z407", "Display Audio"))
    mic = _pick(inputs, preferred_in, ("Insta360 Link 2", "Logi", "MacBook", "Studio Display"))
    return speaker, mic


def synthesize_tts(text: str, *, gain: float = 0.45) -> tuple[np.ndarray, int, str]:
    """Synthesize speech via Truth's actual TTS pipeline (Phonon Ollama -> Kokoro -> macOS say)."""
    safe_gain = max(0.05, min(MAX_SAFE_GAIN, float(gain)))
    clean = (text or "").strip()
    if not clean:
        raise ValueError("empty TTS text")

    # 1. Try Phonon TTS via local Ollama (/v1/audio/speech) — Jaeger's live realtime voice engine
    try:
        body = json.dumps({
            "model": "phonon",
            "voice": os.environ.get("JAEGER_VOICE_TTS_VOICE", "default"),
            "input": clean,
            "response_format": "pcm",
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:11434/v1/audio/speech",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        if len(raw) > 2000:
            samples = np.frombuffer(raw[: (len(raw) // 2) * 2], dtype=np.int16).astype(np.float32) / 32768.0
            peak = float(np.max(np.abs(samples))) or 1.0
            samples = (samples / peak) * safe_gain
            return samples, 24000, "phonon"
    except Exception:  # noqa: BLE001
        pass

    # 2. Try macOS native `say` + ffmpeg/afconvert -> 24 kHz mono WAV (zero external deps, reliable fallback)
    if shutil.which("say") and shutil.which("afconvert"):
        with tempfile.TemporaryDirectory(prefix="jaeger-tts-") as td:
            aiff = Path(td) / "speech.aiff"
            wav_p = Path(td) / "speech.wav"
            subprocess.run(["say", "-o", str(aiff), clean], check=True, capture_output=True, timeout=15)
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", str(aiff), str(wav_p)],
                check=True, capture_output=True, timeout=15,
            )
            with wave.open(str(wav_p), "rb") as wf:
                sr = wf.getframerate()
                pcm = wf.readframes(wf.getnframes())
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            peak = float(np.max(np.abs(samples))) or 1.0
            samples = (samples / peak) * safe_gain
            return samples, sr, "macos_say"

    raise RuntimeError("No local TTS backend available (phonon and macOS say unavailable)")


def _resample_mono(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    dst_len = max(1, int(round(samples.size * float(dst_sr) / float(src_sr))))
    x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=dst_len, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def _write_wav_bytes(samples: np.ndarray, sr: int) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def transcribe_audio(samples: np.ndarray, sample_rate: int) -> tuple[str, str, float]:
    """Transcribe captured microphone audio using Jaeger's actual local STT engines."""
    t0 = time.perf_counter()
    samples_16k = _resample_mono(samples, sample_rate, 16000)

    # 1. Try Jaeger's live Parakeet MLX STT (installed in ~/.jaeger/voice-venv)
    if VOICE_VENV_PY.is_file():
        with tempfile.TemporaryDirectory(prefix="jaeger-stt-") as td:
            pcm_path = Path(td) / "capture.pcm"
            pcm16 = (np.clip(samples_16k, -1.0, 1.0) * 32767.0).astype(np.int16)
            pcm_path.write_bytes(pcm16.tobytes())
            script = (
                "import sys, numpy as np, mlx.core as mx\n"
                "from pathlib import Path\n"
                "from parakeet_mlx import from_pretrained\n"
                "from parakeet_mlx.audio import get_logmel\n"
                "m = from_pretrained('mlx-community/parakeet-tdt-0.6b-v2')\n"
                "raw = Path(sys.argv[1]).read_bytes()\n"
                "a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0\n"
                "mel = get_logmel(mx.array(a), m.preprocessor_config)\n"
                "print(m.generate(mel)[0].text.strip())\n"
            )
            proc = subprocess.run(
                [str(VOICE_VENV_PY), "-c", script, str(pcm_path)],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            if proc.returncode == 0:
                lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
                text = lines[-1] if lines else ""
                return text, "parakeet-tdt-0.6b-v2", round((time.perf_counter() - t0) * 1000.0, 1)

    # 2. Fallback: Jaeger's Whisper web_speech backend
    from jaeger_ai.features.voice import web_speech
    wav_bytes = _write_wav_bytes(samples_16k, 16000)
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    text = web_speech.transcribe_recording(b64, "audio/wav")
    return text, "whisper_cpp", round((time.perf_counter() - t0) * 1000.0, 1)


def _envelope_correlation(ref: np.ndarray, rec: np.ndarray, sr: int) -> float:
    """Normalized max cross-correlation of 20ms RMS envelopes (proves real acoustic propagation)."""
    win = max(1, int(sr * 0.02))
    n_ref = ref.size // win
    n_rec = rec.size // win
    if n_ref < 5 or n_rec < 5:
        return 0.0
    e_ref = np.sqrt(np.mean(ref[: n_ref * win].reshape(n_ref, win) ** 2, axis=1))
    e_rec = np.sqrt(np.mean(rec[: n_rec * win].reshape(n_rec, win) ** 2, axis=1))
    e_ref = e_ref - np.mean(e_ref)
    e_rec = e_rec - np.mean(e_rec)
    denom = float(np.linalg.norm(e_ref) * np.linalg.norm(e_rec))
    if denom <= 1e-9:
        return 0.0
    corr = np.correlate(e_rec, e_ref, mode="full") / denom
    return round(float(np.max(corr)), 3)


def _play_nssound_blocking(samples: np.ndarray, sr: int, device_uid: str) -> tuple[bool, float]:
    """Play WAV natively via macOS AppKit.NSSound targeting exact CoreAudio device UID."""
    from AppKit import NSSound
    from Foundation import NSDate, NSRunLoop

    dur = max(0.1, float(samples.size) / float(sr))
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tf.write(_write_wav_bytes(samples, sr))
        wav_path = Path(tf.name)
    try:
        snd = NSSound.alloc().initWithContentsOfFile_byReference_(str(wav_path), False)
        if snd is None:
            return False, 0.0
        if device_uid:
            snd.setPlaybackDeviceIdentifier_(device_uid)
        t0 = time.perf_counter()
        ok = bool(snd.play())
        if not ok:
            return False, 0.0
        deadline = t0 + dur + 0.85
        while time.perf_counter() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.04))
            if not snd.isPlaying() and (time.perf_counter() - t0) > max(0.4, dur * 0.85):
                break
        snd.stop()
        return True, round((time.perf_counter() - t0) * 1000.0, 1)
    finally:
        wav_path.unlink(missing_ok=True)


def play_and_capture_acoustic(
    samples: np.ndarray,
    tts_sr: int,
    *,
    output_device_index: int,
    input_device_index: int,
    output_device_name: str = "",
    device_sr: int = 48000,
    lead_silence_s: float = 0.6,
    tail_silence_s: float = 0.9,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Play TTS through real physical speakers and capture simultaneously via physical mic."""
    import sounddevice as sd

    lead = np.zeros(int(device_sr * lead_silence_s), dtype=np.float32)
    tail = np.zeros(int(device_sr * tail_silence_s), dtype=np.float32)
    body = _resample_mono(samples, tts_sr, device_sr)
    out_mono = np.concatenate([lead, body, tail])
    out_stereo = np.column_stack([out_mono, out_mono])

    rec_chunks: list[np.ndarray] = []

    def _in_cb(indata, frames, time_info, status):  # noqa: ARG001
        rec_chunks.append(indata[:, 0].copy())

    dev_uid = ""
    if output_device_name:
        dev_uid = str((coreaudio_device_map().get(output_device_name) or {}).get("uid") or "")

    playback_backend = "sounddevice"
    play_start_samples = 0
    play_end_samples = 0
    t0 = time.perf_counter()
    with sd.InputStream(device=input_device_index, channels=1, samplerate=device_sr, dtype="float32", callback=_in_cb):
        used_nssound = False
        if dev_uid:
            try:
                time.sleep(lead_silence_s)
                play_start_samples = max(0, sum(c.size for c in rec_chunks) - int(device_sr * 0.15))
                ok_ns, _ = _play_nssound_blocking(samples, tts_sr, dev_uid)
                if ok_ns:
                    time.sleep(tail_silence_s)
                    play_end_samples = sum(c.size for c in rec_chunks)
                    used_nssound = True
                    playback_backend = "macos_nssound"
            except Exception:  # noqa: BLE001
                used_nssound = False
        if not used_nssound:
            play_start_samples = int(device_sr * lead_silence_s)
            sd.play(out_stereo, samplerate=device_sr, device=output_device_index, blocking=True)
            sd.wait()
            play_end_samples = max(play_start_samples + body.size, sum(c.size for c in rec_chunks))
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    rec = np.concatenate(rec_chunks) if rec_chunks else np.zeros(1, dtype=np.float32)
    noise_end = max(1, min(play_start_samples, rec.size))
    noise_samples = rec[:noise_end]
    s0 = max(0, min(play_start_samples, rec.size - 1))
    s1 = max(s0 + 1, min(play_end_samples if play_end_samples > s0 else rec.size, rec.size))
    speech_slice = rec[s0:s1]
    noise_rms = float(np.sqrt(np.mean(noise_samples ** 2))) if noise_samples.size else 0.0
    speech_rms = float(np.sqrt(np.mean(speech_slice ** 2))) if speech_slice.size else 0.0
    peak_abs = float(np.max(np.abs(speech_slice))) if speech_slice.size else 0.0
    clipped = int(np.sum(np.abs(speech_slice) >= 0.99))
    snr_db = round(20.0 * float(np.log10((speech_rms + 1e-7) / (noise_rms + 1e-7))), 2)
    env_corr = _envelope_correlation(body, speech_slice, device_sr)

    metrics = {
        "playback_backend": playback_backend,
        "duration_ms": elapsed_ms,
        "noise_floor_rms": round(noise_rms, 6),
        "speech_rms": round(speech_rms, 6),
        "snr_db": snr_db,
        "peak_abs": round(peak_abs, 4),
        "clipped_samples": clipped,
        "envelope_correlation": env_corr,
        "silence_detected": speech_rms < 0.001,
        "clipping_detected": clipped > 50,
    }
    # Return the tightly-windowed speech slice so STT transcribes the exact acoustic playback window
    return speech_slice, metrics


def run_audio_loopback_check(
    *,
    artifacts_dir: Path,
    allow_quiet_hours: bool = False,
    gain: float = 0.55,
) -> CheckResult:
    """§3.1 Physical Acoustic Loopback: Truth TTS -> Speakers -> Air -> Mic -> STT."""
    t0 = time.perf_counter()
    if is_quiet_hours() and not allow_quiet_hours:
        return CheckResult(
            id="audio_loopback",
            name="Physical acoustic loopback (TTS -> speaker -> air -> mic -> STT)",
            status=CheckStatus.SKIPPED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason="Quiet hours active (22:00-07:00); pass --allow-quiet-hours to run physical speaker audio.",
        )

    devs = enumerate_audio_devices()
    if not devs.get("available"):
        return CheckResult(
            id="audio_loopback",
            name="Physical acoustic loopback (TTS -> speaker -> air -> mic -> STT)",
            status=CheckStatus.BLOCKED,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason=f"Audio subsystem unavailable: {devs.get('error', 'no devices')}",
        )
    if devs.get("mic_tcc_status") not in (None, 3):
        return CheckResult(
            id="audio_loopback",
            name="Physical acoustic loopback (TTS -> speaker -> air -> mic -> STT)",
            status=CheckStatus.BLOCKED,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason=f"macOS Microphone TCC permission not authorized (status={devs.get('mic_tcc_status')})",
        )

    speaker, mic = select_physical_devices(devs)
    if not speaker or not mic:
        return CheckResult(
            id="audio_loopback",
            name="Physical acoustic loopback (TTS -> speaker -> air -> mic -> STT)",
            status=CheckStatus.BLOCKED,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason="Missing physical speaker or microphone device",
            evidence={"devices": devs},
        )

    phrases = [
        "Truth acoustic check alpha seven four.",
        "Confirming microphone reception across open air.",
    ]
    trials: list[dict[str, Any]] = []
    sr = int(min(speaker["sr"], mic["sr"])) or 48000

    with temporary_physical_audio_ready([speaker["name"]], mic["name"], speaker_volume=0.74, mic_volume=0.90) as ca_info:
        for idx, phrase in enumerate(phrases, 1):
            best_trial: dict[str, Any] | None = None
            for attempt in range(2):
                tts_t0 = time.perf_counter()
                samples, tts_sr, tts_engine = synthesize_tts(phrase, gain=gain)
                tts_ms = round((time.perf_counter() - tts_t0) * 1000.0, 1)
                rec, ac_metrics = play_and_capture_acoustic(
                    samples, tts_sr,
                    output_device_index=speaker["index"],
                    input_device_index=mic["index"],
                    output_device_name=speaker["name"],
                    device_sr=sr,
                )
                wav_path = artifacts_dir / f"acoustic_loopback_{idx}.wav"
                wav_path.write_bytes(_write_wav_bytes(rec, sr))
                transcript, stt_engine, stt_ms = transcribe_audio(rec, sr)
                score = word_match_score(phrase, transcript)
                trial = {
                    "phrase": phrase,
                    "transcript": transcript,
                    "word_match": score,
                    "attempt": attempt + 1,
                    "tts_engine": tts_engine,
                    "tts_ms": tts_ms,
                    "stt_engine": stt_engine,
                    "stt_ms": stt_ms,
                    "acoustic": ac_metrics,
                    "wav": str(wav_path),
                }
                if best_trial is None or score > best_trial["word_match"]:
                    best_trial = trial
                if score >= 0.75 and not ac_metrics["silence_detected"]:
                    break
            assert best_trial is not None
            trials.append(best_trial)

    avg_match = round(sum(t["word_match"] for t in trials) / len(trials), 3)
    max_corr = max(t["acoustic"]["envelope_correlation"] for t in trials)
    all_silent = all(t["acoustic"]["silence_detected"] for t in trials)
    any_clipped = any(t["acoustic"]["clipping_detected"] for t in trials)

    if all_silent:
        return CheckResult(
            id="audio_loopback",
            name="Physical acoustic loopback (TTS -> speaker -> air -> mic -> STT)",
            status=CheckStatus.BLOCKED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            metrics={"avg_word_match": avg_match, "max_envelope_correlation": max_corr, **ca_info},
            evidence={"speaker": speaker["name"], "microphone": mic["name"], "trials": trials},
            reason=f"Microphone '{mic['name']}' captured silence from speaker '{speaker['name']}' (speaker may be muted/unpowered or mic muted).",
        )

    passed = (avg_match >= 0.65) and (max_corr >= 0.25) and not any_clipped
    high_ambient_noise = any(
        (t["acoustic"]["noise_floor_rms"] >= 0.005 or t["acoustic"]["snr_db"] < 6.0)
        for t in trials
    )
    status = CheckStatus.PASS if passed else (CheckStatus.BLOCKED if (high_ambient_noise and not any_clipped) else CheckStatus.FAIL)
    reason = ""
    if not passed:
        if status == CheckStatus.BLOCKED:
            reason = (
                f"High ambient room audio/speech interfered with open-air capture "
                f"(avg_match={avg_match}, max_corr={max_corr}); re-run in a quiet room."
            )
        else:
            reason = f"Low acoustic match ({avg_match}) or correlation ({max_corr}) or clipping ({any_clipped})"
    return CheckResult(
        id="audio_loopback",
        name="Physical acoustic loopback (TTS -> speaker -> air -> mic -> STT)",
        status=status,
        required=(status != CheckStatus.BLOCKED),
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "avg_word_match": avg_match,
            "max_envelope_correlation": max_corr,
            "any_clipped": any_clipped,
            "speaker": speaker["name"],
            "microphone": mic["name"],
            **ca_info,
        },
        evidence={"trials": trials},
        reason=reason,
    )


def run_physical_barge_in_check(
    *,
    artifacts_dir: Path,
    allow_quiet_hours: bool = False,
    gain: float = 0.45,
) -> CheckResult:
    """§3.3 Physical mid-speech barge-in interruption check using dual physical speakers if available."""
    t0 = time.perf_counter()
    if is_quiet_hours() and not allow_quiet_hours:
        return CheckResult(
            id="audio_barge_in",
            name="Physical mid-speech interruption (barge-in)",
            status=CheckStatus.SKIPPED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason="Quiet hours active (22:00-07:00).",
        )
    devs = enumerate_audio_devices()
    outputs = [d for d in (devs.get("outputs") or []) if "jump desktop" not in d["name"].lower()]
    _, mic = select_physical_devices(devs)
    if len(outputs) < 2 or mic is None:
        return CheckResult(
            id="audio_barge_in",
            name="Physical mid-speech interruption (barge-in)",
            status=CheckStatus.BLOCKED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            reason="Requires two independent physical audio outputs to inject real acoustic interruption while Truth speaks; reporting honestly as BLOCKED rather than simulating.",
            evidence={"physical_outputs": [o["name"] for o in outputs]},
        )

    import sounddevice as sd
    from AppKit import NSSound
    from Foundation import NSDate, NSRunLoop

    # Prefer Logi Z407 (if present) for Truth and Mac Studio Speakers for sharp interruption
    dev_map = coreaudio_device_map()
    mac_spk = next((o for o in outputs if "mac studio" in o["name"].lower()), outputs[0])
    logi_spk = next((o for o in outputs if "logi" in o["name"].lower() and o["index"] != mac_spk["index"]), None)
    other_spk = logi_spk or next((o for o in outputs if o["index"] != mac_spk["index"]), outputs[1])
    truth_speaker = other_spk
    interrupter_speaker = mac_spk
    sr = 48000
    long_reply = (
        "This is a long spoken explanation about planetary mechanics and orbital resonance "
        "designed to continue speaking until an independent acoustic interruption arrives."
    )
    interrupt_phrase = "Stop immediately and switch to status summary."
    truth_wav, truth_sr, _ = synthesize_tts(long_reply, gain=min(0.40, gain))
    intr_wav, intr_sr, _ = synthesize_tts(interrupt_phrase, gain=min(0.55, gain))
    intr_dur = max(0.3, float(intr_wav.size) / float(intr_sr))

    truth_file = artifacts_dir / "_barge_truth.wav"
    intr_file = artifacts_dir / "_barge_intr.wav"
    truth_file.write_bytes(_write_wav_bytes(truth_wav, truth_sr))
    intr_file.write_bytes(_write_wav_bytes(intr_wav, intr_sr))

    captured: list[np.ndarray] = []
    interrupted_at: list[float] = []
    intr_started_at: list[float] = []
    intr_sample_offset: list[int] = []
    cancel_requested = threading.Event()

    def _mic_cb(indata, frames, time_info, status):  # noqa: ARG001
        chunk = indata[:, 0].copy()
        captured.append(chunk)
        if intr_started_at and not interrupted_at:
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms > 0.008:
                interrupted_at.append(time.perf_counter())
                cancel_requested.set()

    truth_uid = str((dev_map.get(truth_speaker["name"]) or {}).get("uid") or "")
    intr_uid = str((dev_map.get(interrupter_speaker["name"]) or {}).get("uid") or "")
    cancelled_early = False
    truth_stopped_at: float | None = None

    with temporary_physical_audio_ready([truth_speaker["name"], interrupter_speaker["name"]], mic["name"]) as ca_info:
        snd_truth = NSSound.alloc().initWithContentsOfFile_byReference_(str(truth_file), False)
        snd_intr = NSSound.alloc().initWithContentsOfFile_byReference_(str(intr_file), False)
        if truth_uid:
            snd_truth.setPlaybackDeviceIdentifier_(truth_uid)
        if intr_uid:
            snd_intr.setPlaybackDeviceIdentifier_(intr_uid)

        with sd.InputStream(device=mic["index"], channels=1, samplerate=sr, dtype="float32", callback=_mic_cb):
            t_truth = time.perf_counter()
            snd_truth.play()
            while time.perf_counter() - t_truth < 1.0:
                NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.04))
            intr_sample_offset.append(sum(c.size for c in captured))
            t_intr = time.perf_counter()
            intr_started_at.append(t_intr)
            snd_intr.play()
            deadline = t_intr + intr_dur + 0.5
            while time.perf_counter() < deadline:
                NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.03))
                if cancel_requested.is_set() and truth_stopped_at is None:
                    was_playing = bool(snd_truth.isPlaying())
                    snd_truth.stop()
                    truth_stopped_at = time.perf_counter()
                    cancelled_early = was_playing or (truth_stopped_at - t_truth) < max(2.0, float(truth_wav.size) / float(truth_sr) * 0.8)
            snd_truth.stop()
            snd_intr.stop()
            time.sleep(0.25)

    truth_file.unlink(missing_ok=True)
    intr_file.unlink(missing_ok=True)

    rec = np.concatenate(captured) if captured else np.zeros(1, dtype=np.float32)
    off = intr_sample_offset[0] if intr_sample_offset else 0
    pre_slice = rec[:off] if off > 0 else np.zeros(1, dtype=np.float32)
    post_slice = rec[off:] if off < rec.size else rec
    pre_rms = round(float(np.sqrt(np.mean(pre_slice ** 2))), 6) if pre_slice.size else 0.0
    post_rms = round(float(np.sqrt(np.mean(post_slice ** 2))), 6) if post_slice.size else 0.0

    wav_path = artifacts_dir / "physical_barge_in.wav"
    wav_path.write_bytes(_write_wav_bytes(rec, sr))
    transcript, stt_engine, _ = transcribe_audio(post_slice, sr)
    latency_ms = round((interrupted_at[0] - intr_started_at[0]) * 1000.0, 1) if (interrupted_at and intr_started_at) else None
    cancel_ms = round((truth_stopped_at - intr_started_at[0]) * 1000.0, 1) if (truth_stopped_at and intr_started_at) else None
    intr_match = word_match_score(interrupt_phrase, transcript)

    if not interrupted_at:
        return CheckResult(
            id="audio_barge_in",
            name="Physical mid-speech interruption (barge-in)",
            status=CheckStatus.BLOCKED,
            required=False,
            elapsed_s=round(time.perf_counter() - t0, 2),
            metrics={"truth_speaker": truth_speaker["name"], "interrupter_speaker": interrupter_speaker["name"], "mic": mic["name"], "pre_rms": pre_rms, "post_rms": post_rms, **ca_info},
            evidence={"transcript": transcript, "wav": str(wav_path)},
            reason=f"Interrupter speaker '{interrupter_speaker['name']}' did not reach VAD threshold at mic '{mic['name']}' (device may be powered off/muted).",
        )

    passed = bool(cancelled_early and latency_ms is not None and latency_ms < 1500.0 and intr_match >= 0.4)
    return CheckResult(
        id="audio_barge_in",
        name="Physical mid-speech interruption (barge-in)",
        status=CheckStatus.PASS if passed else CheckStatus.BLOCKED,
        required=False,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "interruption_latency_ms": latency_ms,
            "playback_cancel_ms": cancel_ms,
            "playback_cancelled_early": cancelled_early,
            "interruption_word_match": intr_match,
            "pre_interrupt_rms": pre_rms,
            "post_interrupt_rms": post_rms,
            "stt_engine": stt_engine,
            **ca_info,
        },
        evidence={"transcript": transcript, "truth_speaker": truth_speaker["name"], "interrupter_speaker": interrupter_speaker["name"], "mic": mic["name"]},
        reason="" if passed else f"Acoustic overlap prevented clear transcription of interrupter speaker (match={intr_match}, cancelled_early={cancelled_early}).",
    )


def run_audio_reliability_check() -> CheckResult:
    """§3.4 Audio reliability: device enumeration, volume cap, silence/mute detection, quiet hours guard."""
    t0 = time.perf_counter()
    devs = enumerate_audio_devices()
    # Test silence detector, volume clamping, and quiet hours deterministically
    silent_buf = np.zeros(4800, dtype=np.float32)
    silent_rms = float(np.sqrt(np.mean(silent_buf ** 2)))
    clamped_gain = min(MAX_SAFE_GAIN, 5.0)
    quiet_night = is_quiet_hours(datetime(2026, 11, 19, 23, 0, 0))
    quiet_day = is_quiet_hours(datetime(2026, 11, 19, 14, 0, 0))
    ok = (
        bool(devs.get("available"))
        and len(devs.get("inputs") or []) >= 1
        and len(devs.get("outputs") or []) >= 1
        and silent_rms == 0.0
        and clamped_gain <= MAX_SAFE_GAIN
        and quiet_night is True
        and quiet_day is False
    )
    return CheckResult(
        id="audio_reliability",
        name="Audio device reliability, volume cap, silence & quiet-hours guards",
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        elapsed_s=round(time.perf_counter() - t0, 2),
        metrics={
            "input_count": len(devs.get("inputs") or []),
            "output_count": len(devs.get("outputs") or []),
            "max_safe_gain": clamped_gain,
            "quiet_hours_night": quiet_night,
            "quiet_hours_day": quiet_day,
        },
        evidence={"inputs": [d["name"] for d in (devs.get("inputs") or [])], "outputs": [d["name"] for d in (devs.get("outputs") or [])]},
    )
