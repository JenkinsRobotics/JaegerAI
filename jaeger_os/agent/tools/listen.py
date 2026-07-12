"""Microphone capture + Whisper transcription as an agent tool.

  • listen(seconds, model)  — record N seconds of mic audio, transcribe,
                              return the text.

A one-shot, atomic alternative to the ``--voice`` daemon. The mic is
opened, recorded, and closed inside the call — no always-on listening,
no background thread. The Whisper model is cached at module level so
repeated calls don't reload weights.
"""

from __future__ import annotations

import threading as _threading
import time
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function


# Reuse the same default the voice daemon uses for its "accurate" pass —
# medium.en strikes the sharpest quality/latency balance for English on
# Apple Silicon. Override by passing ``model=...`` on the call.
_DEFAULT_MODEL = "medium.en"
_SAMPLE_RATE = 16000
_MIN_SECONDS = 1
_MAX_SECONDS = 60

# Cache the Whisper model across calls — first call pays the load cost
# (~3-5s for medium.en), subsequent calls are decode-only.
# The lock makes load + swap atomic: with multi-instance agents
# (delegate sub-agents, deep think) two concurrent ``listen`` calls
# could otherwise race the cache — one swapping in a different model
# while the other is mid-transcribe.
_cached_model: Any = None
_cached_model_name: str | None = None
_model_lock = _threading.Lock()


def _get_model(name: str) -> Any:
    """Lazy-load + memoize the Whisper model. Re-loads when the caller
    asks for a different model name (rare; usually one model per session).
    Thread-safe — see ``_model_lock``."""
    global _cached_model, _cached_model_name
    with _model_lock:
        if _cached_model is not None and _cached_model_name == name:
            return _cached_model
        from pywhispercpp.model import Model
        _cached_model = Model(
            name,
            print_realtime=False,
            print_progress=False,
            single_segment=False,
            no_context=True,
        )
        _cached_model_name = name
        return _cached_model


def warm_listen() -> dict[str, Any]:
    """Pre-load AND prime Whisper so the first ``listen`` call doesn't
    pay JIT / kernel-selection overhead in addition to weight load.

    Two stages, matching the Kokoro warm-up:

      1. ``_get_model()`` — load weights (~3–5s cold).
      2. Run a real ``transcribe`` over a short silent buffer so the
         decoder graph + numpy/ggml kernels are picked + cached. The
         transcript is discarded; the side-effect of pipeline priming
         is what we want.

    Without #2 the first real mic capture pays the kernel-selection
    cost mid-decode, which on Apple Silicon shows up as the first
    transcription occasionally producing garbled tokens before the
    pipeline settles. Idempotent.
    """
    started = time.perf_counter()
    load_s = 0.0
    prime_s = 0.0
    try:
        t0 = time.perf_counter()
        model = _get_model(_DEFAULT_MODEL)
        load_s = time.perf_counter() - t0

        # Real decode on a short silent buffer. ``transcribe`` accepts
        # a numpy float32 array at SAMPLE_RATE. One second of silence
        # exercises the full pipeline without recording audio.
        t1 = time.perf_counter()
        try:
            import numpy as np
            silence = np.zeros(_SAMPLE_RATE, dtype=np.float32)
            # pywhispercpp's transcribe() signature — quietly absorb
            # any unexpected exception so a priming failure can't
            # block boot.
            _ = model.transcribe(silence)
        except Exception:  # noqa: BLE001 — priming is best-effort
            pass
        prime_s = time.perf_counter() - t1
    except Exception as exc:
        return {"warmed": False, "model": _DEFAULT_MODEL, "reason": str(exc)}
    return {
        "warmed": True, "model": _DEFAULT_MODEL,
        "seconds": round(time.perf_counter() - started, 3),
        "load_s": round(load_s, 3),
        "prime_s": round(prime_s, 3),
    }


def listen(seconds: int = 5, model: str = _DEFAULT_MODEL) -> dict[str, Any]:
    """Record ``seconds`` of microphone audio and return the transcript.

    Tier-1 (microphone access). The mic is opened, recorded, and closed
    inside this call — no always-on listening. For the always-on
    conversation loop, launch ``python -m jaeger_os --voice`` instead.

    Returns ``{ok, transcript, seconds, model, elapsed_s}`` on success
    or ``{ok: False, error: ...}`` on capture / transcribe failure.
    """
    if not isinstance(seconds, int) or seconds < _MIN_SECONDS:
        return {"ok": False, "error": f"seconds must be an int >= {_MIN_SECONDS}"}
    if seconds > _MAX_SECONDS:
        return {
            "ok": False,
            "error": f"seconds capped at {_MAX_SECONDS}; longer captures "
                     "should use the --voice daemon",
        }
    try:
        import numpy as np
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"numpy missing ({exc})",
        }
    # 0.8.1 field bug #2: boot's voice warm runs in the background now
    # (main.py's warm_plugins_async); a listen() landing before it
    # finishes still works (``_model_lock`` above makes this call wait
    # for an in-flight warm load rather than racing it) — just say so.
    try:
        import sys as _sys
        from jaeger_os.main import voice_warm_status
        status = voice_warm_status()
        if status == "voice: warming…":
            print(f"[jaeger] {status} — listen() will wait for it to finish",
                  file=_sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 — status feedback is best-effort
        pass

    try:
        whisper = _get_model(model)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"whisper load failed: {exc}"}

    started = time.perf_counter()
    audio = None

    # 0.3.0: prefer the avaudio_io InputStream on macOS — kills the
    # PortAudio wedging bug class.  Falls back to sounddevice on
    # other platforms or if the bridge can't load.
    import sys as _sys
    if _sys.platform == "darwin":
        try:
            audio = _record_via_avaudio(seconds, np)
        except Exception as exc:  # noqa: BLE001
            print(f"[listen] avaudio backend unavailable ({exc}); "
                  "falling back to sounddevice", file=_sys.stderr, flush=True)

    if audio is None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            return {
                "ok": False,
                "error": f"audio capture deps missing ({exc}); "
                         "install with `pip install -e \".[voice]\"`",
            }
        try:
            audio = sd.rec(
                int(seconds * _SAMPLE_RATE),
                samplerate=_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocking=True,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"mic capture failed: {exc}"}

    # pywhispercpp expects a 1D float32 array at 16 kHz.
    samples = np.asarray(audio, dtype="float32").reshape(-1)
    try:
        segments = whisper.transcribe(samples)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"transcribe failed: {exc}"}

    text = " ".join((s.text or "").strip() for s in segments).strip()
    elapsed = time.perf_counter() - started
    return {
        "ok": True,
        "transcript": text,
        "seconds": seconds,
        "model": model,
        "elapsed_s": round(elapsed, 3),
    }


def _record_via_avaudio(seconds: int, np_module):
    """Blocking capture via the avaudio_io InputStream — collects
    ``seconds * _SAMPLE_RATE`` frames into a NumPy array and returns
    it.  Raises on bridge failure so the caller can fall back to
    sounddevice."""
    import threading as _threading

    from jaeger_os.core.audio.avaudio_io import InputStream as _AVInputStream

    target = int(seconds * _SAMPLE_RATE)
    blocksize = 320  # 20 ms @ 16 kHz
    buf = []
    captured = [0]
    done = _threading.Event()

    def _cb(indata, frames, _t, _s):
        if done.is_set():
            return
        buf.append(indata.copy())
        captured[0] += frames
        if captured[0] >= target:
            done.set()

    stream = _AVInputStream(
        samplerate=_SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        callback=_cb,
    )
    try:
        stream.start()
        if not done.wait(timeout=seconds + 3.0):
            raise RuntimeError(
                f"avaudio capture timed out after {seconds + 3.0:.1f}s"
            )
    finally:
        stream.close()

    if not buf:
        raise RuntimeError("avaudio capture produced no audio")
    audio = np_module.concatenate(buf, axis=0)[:target]
    return audio


# ── Agent-tool wrapper (migrated from main.py::_register_builtins) ──


@register_tool_from_function(name="listen")
def _t_listen(seconds: int = 5) -> dict:
    """Record N seconds of microphone audio and return the transcript.

    Use when the user asks you to listen, or when you need to capture
    spoken input mid-chat. Atomic: mic opens, records, closes — no
    always-on listening. Cap is 60s; for hands-free conversation, tell
    the user to launch ``python -m jaeger_os --voice`` instead.

    Returns ``{ok, transcript, seconds, model, elapsed_s}`` on success."""
    return listen(seconds=seconds)
