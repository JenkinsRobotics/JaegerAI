"""Kokoro TTS — synthesizes text via Kokoro KPipeline, plays through sounddevice.

This module is the plugin's actual implementation. It's a relocation of
the pipeline + playback code that used to live in `core/tools/speak.py`.
The agent-callable `speak()` / `speak_file()` Tools still live there, but
they now delegate into this plugin.

Why a plugin and not a core tool? Per the vocabulary contract, this
component bridges the agent to an external library (`kokoro`) + external
model files + speaker hardware. That's the plugin pattern. When we deploy
to robot hardware, this same plugin will graduate to a separate-process
ZMQ node on the Jetson while the rest of the framework stays put.

Public surface (consumed by core/tools/speak.py):
  • KokoroTTS()              — lazy-loaded singleton in practice
  • .warm()                  — pre-load weights so the first speak() is fast
  • .speak(text)             — synthesize + play, returns result dict
  • Module constants         — KOKORO_VOICE, KOKORO_LANG, KOKORO_SAMPLE_RATE
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any


KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"
KOKORO_SAMPLE_RATE = 24000
# Sample rate the AEC reference buffer is expected to run at. AEC math
# requires near (mic) and far (TTS playback) at the same sample rate;
# the mic captures at 16 kHz, so Kokoro's 24 kHz output gets resampled
# down before being pushed to the reference buffer.
REFERENCE_SAMPLE_RATE = 16000


# ---------------------------------------------------------------------------
# Markdown stripping for TTS — agents emit asterisks, code fences, link
# syntax, etc., and Kokoro reads them literally otherwise.
# ---------------------------------------------------------------------------
def clean_for_tts(text: str) -> str:
    """Strip markdown the agent might emit so TTS doesn't read it literally.
    Removes code fences, inline code backticks, bold/italic asterisks,
    leading list markers, and markdown link syntax (keeping the link text)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"^[\-\*\d\.\)]+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _resample_to_reference_rate(audio_f32):
    """Resample Kokoro's 24 kHz output to the AEC reference sample rate
    (16 kHz). Polyphase keeps the voice band intact and adds well under
    a millisecond of latency."""
    import numpy as np
    from scipy.signal import resample_poly

    if audio_f32.size == 0:
        return np.zeros(0, dtype=np.float32)
    if KOKORO_SAMPLE_RATE == REFERENCE_SAMPLE_RATE:
        return audio_f32.astype(np.float32, copy=False)
    return resample_poly(audio_f32, up=REFERENCE_SAMPLE_RATE, down=KOKORO_SAMPLE_RATE).astype(np.float32)


# ---------------------------------------------------------------------------
# SSML parsing for paced narration
# ---------------------------------------------------------------------------
_SSML_SPEAK_TAG = re.compile(r"</?speak\s*>", re.IGNORECASE)
_SSML_TAG = re.compile(
    r'<break\s+time=["\'](\d+(?:\.\d+)?)\s*(ms|s)["\']\s*/?>|<breath\s*/?>',
    re.IGNORECASE,
)
_BREATH_GAP_MS = 220


def _ssml_segments(text: str):
    """Yield ('text', str) | ('silence_ms', int) chunks."""
    cleaned = _SSML_SPEAK_TAG.sub("", text)
    pos = 0
    for match in _SSML_TAG.finditer(cleaned):
        before = cleaned[pos:match.start()]
        if before.strip():
            yield ("text", before.strip())
        tag = match.group(0).lower()
        if tag.startswith("<break"):
            value = float(match.group(1))
            unit = match.group(2).lower()
            ms = int(value * 1000) if unit == "s" else int(value)
            yield ("silence_ms", ms)
        else:
            yield ("silence_ms", _BREATH_GAP_MS)
        pos = match.end()
    tail = cleaned[pos:]
    if tail.strip():
        yield ("text", tail.strip())


class KokoroTTS:
    """Lazy-loaded Kokoro pipeline + sounddevice playback.

    Single-instance in practice — `core/tools/speak.py` caches one in a
    module global. Thread-safety is intentionally minimal: Kokoro's pipeline
    is not designed for concurrent calls, and the agent's tool surface is
    serialized through the LLM lock anyway.
    """

    def __init__(
        self,
        *,
        voice: str = KOKORO_VOICE,
        lang: str = KOKORO_LANG,
        reference_buffer: Any = None,
    ) -> None:
        self.voice = voice
        self.lang = lang
        self._pipeline: Any = None
        # When set, every played frame is also pushed to this buffer so the
        # STT plugin's AEC can use it as the far-end reference. Without it,
        # AEC sees silence as far-end and barge-in won't work — but plain
        # set_paused()-based playback still works.
        self.reference_buffer = reference_buffer
        # 0.3.0-refactor step 1+2: ONE long-lived output stream for the
        # whole TTS lifetime.  Backend chosen at runtime from
        # ``config.voice.audio_backend`` (default "sounddevice"):
        #   - "sounddevice" : PortAudio path proven by
        #     dev/tools/audio_smoke/voice_assistant_persistent.py
        #   - "avaudio"     : AVAudioEngine path proven by
        #     dev/tools/audio_smoke/voice_assistant_avaudio.py
        # Lazy-opened by ``_ensure_player`` from ``warm()``; closed by
        # ``shutdown()`` at TUI exit.
        from .persistent_player import PersistentKokoroPlayer
        self._PlayerCls = PersistentKokoroPlayer
        self._player: Any = None
        # Operator can override the config-default backend at runtime
        # via ``JAEGER_AUDIO_BACKEND`` for quick A/B testing without
        # editing config.yaml.  Falls through to the config / "sounddevice"
        # default in :meth:`_resolve_backend`.
        self._backend_override = os.environ.get("JAEGER_AUDIO_BACKEND")

    def _resolve_backend(self) -> str:
        """Pick the audio backend for the persistent player.

        Resolution order: env override → instance config → default
        "sounddevice".  Validated against the supported set; an
        unknown name falls back to "sounddevice" with a warning."""
        candidate = self._backend_override
        if not candidate:
            try:
                from jaeger_os.core.context import _require_layout
                from jaeger_os.core.instance.schemas import Config, load_yaml
                layout = _require_layout()
                cfg = load_yaml(layout.config_path, Config)
                vc = getattr(cfg, "voice", None)
                candidate = getattr(vc, "audio_backend", None) if vc else None
            except Exception:  # noqa: BLE001 — config read is best-effort
                candidate = None
        if not candidate:
            candidate = "sounddevice"
        from .persistent_player import PersistentKokoroPlayer
        if candidate not in PersistentKokoroPlayer.SUPPORTED_BACKENDS:
            print(
                f"[kokoro] unknown audio_backend {candidate!r}; "
                f"falling back to 'sounddevice'",
                file=sys.stderr, flush=True,
            )
            return "sounddevice"
        return candidate

    # ── persistent player lifecycle ───────────────────────────────────
    def _ensure_player(self) -> Any:
        """Open the persistent output stream if it isn't already.
        Idempotent; safe to call from warm() AND from the first speak()."""
        if self._player is not None and self._player.is_open():
            return self._player
        backend = self._resolve_backend()
        self._player = self._PlayerCls(
            backend=backend,
            samplerate=KOKORO_SAMPLE_RATE, channels=1,
        )
        self._player.start()
        print(f"[kokoro] persistent output stream open → "
              f"backend={backend!r} device={self._player.device_index} "
              f"name={self._player.device_name!r}",
              file=sys.stderr, flush=True)
        return self._player

    def shutdown(self) -> None:
        """Release the persistent player.  Called from the TUI's
        ``_shutdown`` so the sounddevice stream closes deterministically
        BEFORE Python's interpreter shutdown starts tearing things
        down (avoids the PortAudio-at-Pa_Terminate segfault that bit
        plain 0.2.6).  Idempotent."""
        if self._player is None:
            return
        try:
            self._player.close()
        except Exception:  # noqa: BLE001
            pass
        self._player = None

    # ── pipeline lifecycle ────────────────────────────────────────────
    def _ensure_pipeline(self) -> Any:
        if self._pipeline is None:
            import warnings

            # Kokoro's model build emits noisy torch UserWarnings
            # (LSTM dropout) and FutureWarnings (weight_norm deprecation).
            # They are harmless and not actionable by the user — silence
            # them so a `speak` call doesn't spew a wall of stack-frame
            # text into the TUI.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                warnings.simplefilter("ignore", category=FutureWarning)
                from kokoro import KPipeline
                self._pipeline = KPipeline(
                    lang_code=self.lang, repo_id="hexgrad/Kokoro-82M",
                )
        return self._pipeline

    def warm(self) -> dict[str, Any]:
        """Pre-load Kokoro, prime the synthesis pipeline, AND open the
        persistent audio output stream — all at boot, before any user
        activity / agent inference disturbs PortAudio's CoreAudio state.

        Three stages (0.3.0-refactor step 1):

          1. ``_ensure_pipeline()`` — loads weights (~3–5s cold).
          2. ``_ensure_player()`` — opens the persistent sounddevice
             OutputStream NOW, while we're still in the clean
             post-model-load window the working
             ``voice_assistant_persistent.py`` uses (its
             ``PersistentPlayer.start()`` fires immediately after
             loading the LLM and Kokoro, BEFORE entering the
             conversation loop).  Opening lazily on first speak()
             instead reliably hit PortAudio error -9986
             (paInternalError) inside the TUI.
          3. A real synthesis pass over a short primer phrase, audio
             discarded.  Exercises the full inference graph including
             the MPS / Metal kernel pickers on Apple Silicon — without
             it, the FIRST real user utterance pays the JIT cost,
             which manifested as audible distortion + dropped phonemes
             (a known PyTorch-on-MPS first-batch behaviour).  Runs
             AFTER stage 2 so opening the audio device doesn't have
             to fight whatever Metal context PyTorch sets up.

        Idempotent. Audio is built in memory but never played — we
        don't want a phantom "warming up" sound at boot.
        """
        started = time.perf_counter()
        load_s = 0.0
        prime_s = 0.0
        # Stage 1 — load Kokoro weights (lazy, no inference yet).
        try:
            t0 = time.perf_counter()
            pipe = self._ensure_pipeline()
            # Drain ONE chunk so the model object's internal lazy
            # state is touched — still no real inference.
            for _ in pipe(" ", voice=self.voice):
                break
            load_s = time.perf_counter() - t0
        except Exception as exc:
            return {"warmed": False, "reason": f"pipeline load: {exc}",
                    "load_s": round(load_s, 3),
                    "prime_s": round(prime_s, 3)}

        # Stage 2 — open the persistent OutputStream in the clean
        # post-model-load window.  Failure here is non-fatal: speak()
        # will retry on first use (and surface the error in the result
        # dict so the operator sees it).
        player_device: Any = None
        try:
            self._ensure_player()
            player_device = self._player.device_name if self._player else None
        except Exception as exc:  # noqa: BLE001
            print(
                f"[kokoro] persistent player warm failed ({exc}); "
                "will retry on first speak()",
                file=sys.stderr, flush=True,
            )

        # Stage 3 — REAL primer synthesis (PyTorch MPS warm-up).
        try:
            t1 = time.perf_counter()
            primer = "Hello, this is a warm-up pass. One, two, three."
            import numpy as np
            chunks: list[Any] = []
            for r in pipe(primer, voice=self.voice):
                if r.audio is not None:
                    chunks.append(np.asarray(r.audio, dtype=np.float32))
            # Touch the concatenation path too — the synthesis side of
            # ``speak()`` builds the same shape.
            if chunks:
                _ = np.concatenate(chunks)
            prime_s = time.perf_counter() - t1
        except Exception as exc:
            return {"warmed": False, "reason": f"primer: {exc}",
                    "load_s": round(load_s, 3),
                    "prime_s": round(prime_s, 3),
                    "player_device": player_device}
        total = round(time.perf_counter() - started, 3)
        return {
            "warmed": True, "seconds": total,
            "player_device": player_device,
            "load_s": round(load_s, 3),
            "prime_s": round(prime_s, 3),
        }

    # ── synthesis + playback ──────────────────────────────────────────
    def _synthesize(self, text: str) -> tuple[Any, bool]:
        """Render the text to a single float32 audio buffer. Returns
        (audio, has_ssml). Caller is responsible for playback."""
        import numpy as np

        pipe = self._ensure_pipeline()
        chunks: list[Any] = []
        has_ssml = (
            "<break" in text.lower()
            or "<breath" in text.lower()
            or "<speak" in text.lower()
        )
        if has_ssml:
            for kind, value in _ssml_segments(text):
                if kind == "text":
                    for r in pipe(value, voice=self.voice):
                        if r.audio is not None:
                            chunks.append(np.asarray(r.audio, dtype=np.float32))
                else:
                    n = int(KOKORO_SAMPLE_RATE * value / 1000)
                    if n > 0:
                        chunks.append(np.zeros(n, dtype=np.float32))
        else:
            for r in pipe(text, voice=self.voice):
                if r.audio is not None:
                    chunks.append(np.asarray(r.audio, dtype=np.float32))
        if not chunks:
            return None, has_ssml
        return np.concatenate(chunks), has_ssml

    def speak(self, text: str) -> dict[str, Any]:
        """Synthesize speech with Kokoro and play through the persistent
        sounddevice output.  Supports minimal SSML: <speak>,
        <break time="Xms"/>, <breath/>.

        Streams chunks through the persistent player AS Kokoro produces
        them — chunk N starts playing while chunk N+1 is still being
        synthesized.  Blocks until playback finishes.  Markdown
        (``**bold**``, code fences, link syntax) is stripped before
        synthesis.

        0.3.0-refactor (step 1): rewritten to mirror the working
        ``voice_assistant_persistent.py`` pattern — one long-lived
        OutputStream + chunk queue, no per-utterance device open/close.
        Replaces the old _synthesize → sd.play() per call path which
        was producing PortAudio errors + exit segfaults on macOS 26.5.
        """
        import numpy as np

        cleaned = clean_for_tts(text)
        if not cleaned:
            return {"spoken": False, "reason": "empty text"}

        started = time.perf_counter()
        try:
            player = self._ensure_player()
        except Exception as exc:  # noqa: BLE001
            return {
                "spoken": False,
                "reason": f"player open failed: {exc}",
                "text": cleaned,
            }

        pipe = self._ensure_pipeline()
        has_ssml = (
            "<break" in cleaned.lower()
            or "<breath" in cleaned.lower()
            or "<speak" in cleaned.lower()
        )

        queued_samples = 0

        def _enqueue_chunk(chunk_24k: np.ndarray) -> None:
            """Push to player AND to the AEC far-end buffer (so STT
            can suppress our own voice).  Mirrors the chunk routing
            from play_async()."""
            nonlocal queued_samples
            if chunk_24k.size == 0:
                return
            if self.reference_buffer is not None:
                try:
                    ref = _resample_to_reference_rate(chunk_24k)
                    self.reference_buffer.write(ref)
                except Exception:  # noqa: BLE001 — best effort
                    pass
            player.enqueue(chunk_24k)
            queued_samples += int(chunk_24k.size)

        try:
            if has_ssml:
                for kind, value in _ssml_segments(cleaned):
                    if kind == "text":
                        for r in pipe(value, voice=self.voice):
                            if r.audio is None:
                                continue
                            _enqueue_chunk(
                                np.asarray(r.audio, dtype=np.float32))
                    else:  # silence_ms
                        n = int(KOKORO_SAMPLE_RATE * value / 1000)
                        if n > 0:
                            _enqueue_chunk(np.zeros(n, dtype=np.float32))
            else:
                for r in pipe(cleaned, voice=self.voice):
                    if r.audio is None:
                        continue
                    _enqueue_chunk(np.asarray(r.audio, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            return {
                "spoken": False,
                "reason": f"synthesis failed: {exc}",
                "text": cleaned,
            }

        if queued_samples == 0:
            return {
                "spoken": False,
                "reason": "no audio generated",
                "text": cleaned,
            }

        # Signal end-of-message and block until the audio thread has
        # actually played everything we enqueued.
        player.mark_end()
        if not player.wait_until_drained():
            try:
                player.reset()
            except Exception:  # noqa: BLE001
                try:
                    player.close()
                except Exception:  # noqa: BLE001
                    pass
                self._player = None
            return {
                "spoken": False,
                "reason": "drain timeout",
                "text": cleaned,
                "samples": queued_samples,
            }

        return {
            "spoken": True,
            "text": cleaned,
            "chars": len(cleaned),
            "seconds": round(time.perf_counter() - started, 3),
            "ssml": has_ssml,
            "samples": queued_samples,
            "device": player.device_name,
        }

    # ── async playback (for barge-in) ─────────────────────────────────
    def play_async(self, text: str) -> dict[str, Any]:
        """Like speak(), but returns immediately and supports interruption.

        Kicks off a synthesis thread that streams Kokoro generator chunks
        into the persistent player. Each chunk is pushed to playback AS
        IT'S SYNTHESIZED, not after the whole utterance is rendered — so
        the user can interrupt during synthesis, not just during playback.

        AEC reference audio is resampled from 24 kHz down to 16 kHz before
        being pushed to the reference buffer (which the STT-side AEC reads
        at 16 kHz, the mic's native rate).

        Markdown stripping is applied before synthesis.

        Returns synthesis metadata. To know when playback actually ends,
        poll `is_playing()` or call `wait_until_done()`.
        """
        import numpy as np
        import threading

        cleaned = clean_for_tts(text)
        if not cleaned:
            return {"started": False, "reason": "empty text"}

        synth_started = time.perf_counter()
        try:
            player = self._ensure_player()
        except Exception as exc:  # noqa: BLE001
            return {"started": False, "reason": f"player open failed: {exc}"}

        # Fresh per-utterance cancel flag — set() to stop both synthesis
        # and playback. Threads check it between chunks.
        self._cancel = threading.Event()
        self._stream_done = threading.Event()
        self._async_player = player
        queued_samples = {"n": 0}

        def _enqueue_async_chunk(chunk_24k: np.ndarray) -> None:
            if chunk_24k.size == 0 or self._cancel.is_set():
                return
            if self.reference_buffer is not None:
                try:
                    ref = _resample_to_reference_rate(chunk_24k)
                    self.reference_buffer.write(ref)
                except Exception:  # noqa: BLE001
                    pass
            player.enqueue(chunk_24k)
            queued_samples["n"] += int(chunk_24k.size)

        # Synthesis worker — runs in its own thread so play_async() returns.
        def _synth_loop() -> None:
            pipe = self._ensure_pipeline()
            try:
                has_ssml = (
                    "<break" in cleaned.lower()
                    or "<breath" in cleaned.lower()
                    or "<speak" in cleaned.lower()
                )
                if has_ssml:
                    for kind, value in _ssml_segments(cleaned):
                        if self._cancel.is_set():
                            return
                        if kind == "text":
                            for r in pipe(value, voice=self.voice):
                                if self._cancel.is_set():
                                    return
                                if r.audio is None:
                                    continue
                                _enqueue_async_chunk(
                                    np.asarray(r.audio, dtype=np.float32))
                        else:
                            n = int(KOKORO_SAMPLE_RATE * value / 1000)
                            if n > 0:
                                _enqueue_async_chunk(
                                    np.zeros(n, dtype=np.float32))
                else:
                    for r in pipe(cleaned, voice=self.voice):
                        if self._cancel.is_set():
                            return
                        if r.audio is None:
                            continue
                        _enqueue_async_chunk(
                            np.asarray(r.audio, dtype=np.float32))
            finally:
                if not self._cancel.is_set() and queued_samples["n"] > 0:
                    player.mark_end()
                    if not player.wait_until_drained():
                        try:
                            player.reset()
                        except Exception:  # noqa: BLE001
                            pass
                self._stream_done.set()

        self._synth_thread = threading.Thread(
            target=_synth_loop, daemon=True, name="kokoro-synth",
        )
        self._synth_thread.start()

        return {
            "started": True,
            "text": cleaned,
            "chars": len(cleaned),
            "synth_started_s": round(time.perf_counter() - synth_started, 3),
            "device": player.device_name,
        }

    def _close_stream(self) -> None:
        """Close the legacy async stream if one exists.

        Kept as a compatibility cleanup hook for sessions created by
        older code paths before 0.3.0 switched async playback to the
        persistent player.
        """
        s = getattr(self, "_stream", None)
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
            self._stream = None

    def stop(self) -> None:
        """Stop async playback immediately. Drops the queue, signals
        synthesis to bail, closes the output stream, and clears AEC
        reference. Idempotent."""
        cancel = getattr(self, "_cancel", None)
        if cancel is not None:
            cancel.set()
        player = getattr(self, "_async_player", None) or self._player
        if player is not None:
            try:
                player.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._close_stream()
        done = getattr(self, "_stream_done", None)
        if done is not None:
            done.set()
        if self.reference_buffer is not None:
            self.reference_buffer.clear()

    def is_playing(self) -> bool:
        """True while async playback is active (chunks still queued or
        playing). Polled by the voice loop to know when an async speak
        has finished naturally."""
        s = getattr(self, "_stream", None)
        synth = getattr(self, "_synth_thread", None)
        if synth is not None and synth.is_alive():
            return True
        done = getattr(self, "_stream_done", None)
        if done is not None and not done.is_set():
            return True
        if s is None:
            return False
        try:
            return bool(s.active)
        except Exception:
            return False

    def wait_until_done(self) -> None:
        """Block until async playback finishes naturally (or stop() is called)."""
        done = getattr(self, "_stream_done", None)
        if done is None:
            return
        done.wait(timeout=120.0)
        self._close_stream()


def _resolve_live_device(sd) -> int | None:
    """Re-query the current system default output device each call so
    AirPods/Speakers swaps work mid-session."""
    try:
        info = sd.query_devices(kind="output")
        if isinstance(info, dict) and "index" in info:
            return int(info["index"])
    except Exception:
        pass
    return None


def _bounded_play(sd, audio, *, device, samplerate):
    """Call ``sd.play`` + ``sd.wait`` with a wall-clock timeout.

    0.2.6: ``sd.wait()`` blocks indefinitely. When CoreAudio loses the
    backing device mid-stream (the ``PaMacCore (AUHAL) Error on line
    2747 ... Unspecified Audio Hardware Error`` case), the callback
    thread stops draining but ``wait()`` never returns. The TTS tool
    call hangs, the agent loop blocks because tools are synchronous,
    and the operator's interrupts / steers queue but can't fire until
    the tool comes back. Symptom: ``> tool : text_to_speech`` clock
    climbs past 60s and the TUI is unresponsive.

    Bound the wait to ``audio_length + 5s`` (5s of slop for buffer
    drain). If we hit the cap, call ``sd.stop()`` to force-cancel and
    raise so the outer ``except`` triggers the reinit path. Worst
    case: a TTS line gets cut a few seconds early — far better than
    hanging the agent.
    """
    sd.play(audio, samplerate=samplerate, device=device)
    audio_len_s = len(audio) / float(samplerate)
    timeout_s = max(2.0, audio_len_s + 5.0)
    import time as _time
    deadline = _time.monotonic() + timeout_s
    while True:
        active = False
        try:
            stream = getattr(sd, "_last_callback", None)
            active = bool(stream and stream.stream and stream.stream.active)
        except Exception:
            active = False
        if not active:
            return
        if _time.monotonic() > deadline:
            try:
                sd.stop()
            except Exception:
                pass
            raise RuntimeError(
                f"sd.wait() exceeded {timeout_s:.1f}s for "
                f"{audio_len_s:.1f}s of audio — likely a hung CoreAudio "
                f"stream (PaMacCore AUHAL). Aborted playback."
            )
        _time.sleep(0.05)


def _play_audio_with_live_device(sd, audio, reference_buffer=None):
    """Synchronous play. Pushes audio to the AEC reference buffer (if
    supplied) so STT can cancel echo even on sync paths."""
    # Reference push happens BEFORE play() so the far-end is available
    # the moment the mic callback might fire. Stale reference is fine.
    if reference_buffer is not None:
        try:
            reference_buffer.write(audio)
        except Exception:
            pass

    device = _resolve_live_device(sd)
    try:
        _bounded_play(sd, audio, device=device, samplerate=KOKORO_SAMPLE_RATE)
        return device
    except Exception as first_exc:
        try:
            sd.stop()
        except Exception:
            pass
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        device = _resolve_live_device(sd)
        try:
            _bounded_play(sd, audio, device=device,
                          samplerate=KOKORO_SAMPLE_RATE)
            return device
        except Exception as second_exc:
            try:
                sd.stop()
            except Exception:
                pass
            return {
                "spoken": False,
                "reason": f"playback failed after reinit: {second_exc}",
                "first_error": str(first_exc),
                "device": device,
            }
