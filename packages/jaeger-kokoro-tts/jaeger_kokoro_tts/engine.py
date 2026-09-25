"""Kokoro speech synthesis for the JaegerOS ``tts`` slot.

In an application this engine publishes 24 kHz mono PCM to JaegerOS's
audio driver; the driver is the only component that opens the speaker.
The standalone CLI may instead use the direct persistent player. Both
paths share the same synthesis, cancellation, and drain behavior.

Public surface (consumed by ``node.py``'s ``Synthesizer`` protocol):
  • KokoroTTS()              — lazy-loaded singleton in practice
  • .warm()                  — pre-load weights so the first speak() is fast
  • .speak(text)             — synthesize + play, returns result dict
  • Module constants         — KOKORO_VOICE, KOKORO_LANG, KOKORO_SAMPLE_RATE
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from jaeger_os.app.logging import log
from jaeger_os.core.audio import FarEndReference


KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"
KOKORO_SAMPLE_RATE = 24000

# ---------------------------------------------------------------------------
# HF Hub offline-first boot (0.8.1 field bug #1: "boot never blocks on
# network"). Kokoro's own loader (kokoro/model.py, kokoro/pipeline.py) calls
# huggingface_hub.hf_hub_download() with no local_files_only= — EVERY call
# does an unauthenticated HEAD request against the Hub to check for a newer
# revision before trusting the local cache, even when every required file
# is already on disk (verified: a 37GB-cached instance still stalled boot
# minutes on rate-limited HEADs). Principle: install/update time is when
# the network happens; runtime is offline. If the assets this pipeline
# needs are already cached, force huggingface_hub into offline mode BEFORE
# constructing KPipeline — automatic, no operator config. If something
# required is genuinely missing, leave the Hub reachable (first-run
# download) but log loudly so a slow boot has an obvious cause on the
# console; item 2 (voice warm off the boot critical path) keeps that
# download from wedging the app either way.
_KOKORO_MODEL_FILENAMES = {
    "hexgrad/Kokoro-82M": "kokoro-v1_0.pth",
    "hexgrad/Kokoro-82M-v1.1-zh": "kokoro-v1_1-zh.pth",
}
_HF_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _HF_TRUE_VALUES


def ensure_hf_offline_if_cached(
    repo_id: str = "hexgrad/Kokoro-82M", voice: str = KOKORO_VOICE,
) -> bool:
    """Force ``HF_HUB_OFFLINE`` on for this process when every file Kokoro
    needs for ``repo_id``/``voice`` is already in the local HF cache.
    Cache-index lookups only (``huggingface_hub.try_to_load_from_cache``)
    — no network, cheap enough to call on every pipeline init. Returns
    True when offline mode is (already, or newly) in effect.

    An operator-set ``HF_HUB_OFFLINE`` env var always wins either
    direction — this never overrides an explicit choice.
    """
    if "HF_HUB_OFFLINE" in os.environ:
        return _env_true("HF_HUB_OFFLINE")

    from huggingface_hub import _CACHED_NO_EXIST, try_to_load_from_cache

    required = [
        "config.json",
        _KOKORO_MODEL_FILENAMES.get(repo_id, _KOKORO_MODEL_FILENAMES["hexgrad/Kokoro-82M"]),
        f"voices/{voice}.pt",
    ]
    missing = [
        f for f in required
        if (hit := try_to_load_from_cache(repo_id=repo_id, filename=f)) is None
        or hit is _CACHED_NO_EXIST
    ]
    if missing:
        log("kokoro",
            f"NOT fully cached ({', '.join(missing)} missing for "
            f"{repo_id!r}) — boot will fetch from Hugging Face Hub "
            "(network required; one-time download).", level="warn")
        return False

    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        # constants.HF_HUB_OFFLINE is a module-level global read live by
        # is_offline_mode() — patch it directly too, in case some other
        # import path already pulled in huggingface_hub.constants earlier
        # in this process (env var alone only affects a FIRST import).
        import huggingface_hub.constants as _hf_constants
        _hf_constants.HF_HUB_OFFLINE = True
    except Exception:  # noqa: BLE001 — env var alone still helps
        pass
    # `info`, not `debug`: "is the network on my boot critical path?" is
    # a once-per-boot fact an operator needs on a robot that may have no
    # network at all. Its counterpart below (NOT fully cached) warns, so
    # the two together always say which path boot took.
    log("kokoro", f"{repo_id!r} fully cached — forcing HF_HUB_OFFLINE "
        "(no Hub freshness checks at boot).")
    return True
# ---------------------------------------------------------------------------
# espeak-ng data-path length workaround (0.9 from-scratch-install fix).
#
# ROOT CAUSE (diagnosed empirically, not guessed): the ``espeakng-loader``
# wheel's bundled ``libespeak-ng.dylib`` has a FIXED-SIZE internal C path
# buffer. When ``espeakng_loader.get_data_path()`` (a path inside whatever
# venv's site-packages the wheel happens to be installed into) is longer
# than ~150 characters, ``espeak_Initialize()`` silently fails to use it,
# falls back to the wheel's CI-build-time-baked absolute path (e.g.
# ``<home>/work/espeakng-loader/.../espeak-ng-data``), can't find
# ``phontab`` there, and hard-exits(1) from inside the C library — no
# Python exception, no traceback, just process death. Verified via a
# binary search sweep: identical dylib + data, byte-for-byte, works at a
# 150-char data path and fails at 152. This is why it only ever showed up
# in freshly-built venvs: NOT because the venv is "fresh," but because
# fresh venvs in this project's flow tend to live under longer paths
# (sandboxed CI checkouts, session-scoped scratch dirs) than a long-lived
# hand-built dev venv — a mature venv at a short path never hit it, and a
# fresh venv at a short path never will either (confirmed both ways).
#
# FIX: mirror the loader's dylib + data dir into a short, fixed location
# under /tmp (always short, always present, OS-guaranteed) the first time
# the resolved path is too long, and point phonemizer's EspeakWrapper at
# the mirror instead. Idempotent (checked by mtime), cheap (~20MB copy,
# once), and applied BEFORE kokoro/misaki ever construct a real espeak
# backend (misaki's own module-level ``EspeakWrapper.set_library()`` call
# is harmless — it only sets an override string; the C library isn't
# touched until a backend is actually constructed, which kokoro defers to
# ``KPipeline()`` construction, not import time).
_ESPEAK_SAFE_PATH_LEN = 130  # conservative; empirical break point is ~151
_ESPEAK_SHORT_MIRROR_ROOT = "/tmp/jaeger-espeak-ng"


def ensure_short_espeak_paths() -> None:
    """If espeakng_loader's data path is long enough to hit espeak-ng's
    fixed-size C path buffer, mirror it to a short /tmp path and point
    phonemizer's EspeakWrapper there. No-op (and cheap) otherwise."""
    try:
        import espeakng_loader
    except ImportError:
        return  # not installed — kokoro's own import will fail loudly

    lib_path = espeakng_loader.get_library_path()
    data_path = espeakng_loader.get_data_path()
    if len(data_path) < _ESPEAK_SAFE_PATH_LEN:
        target_lib, target_data = lib_path, data_path
    else:
        import shutil

        mirror = os.path.join(
            _ESPEAK_SHORT_MIRROR_ROOT, f"v{os.path.basename(data_path.rstrip('/'))}"
        )
        target_lib = os.path.join(mirror, os.path.basename(lib_path))
        target_data = os.path.join(mirror, "espeak-ng-data")
        marker = os.path.join(mirror, ".source")
        needs_copy = not (
            os.path.isfile(target_lib)
            and os.path.isdir(target_data)
            and os.path.isfile(marker)
            and open(marker).read().strip() == lib_path
        )
        if needs_copy:
            os.makedirs(mirror, exist_ok=True)
            shutil.copy2(lib_path, target_lib)
            data_target_tmp = target_data + ".tmp"
            if os.path.isdir(data_target_tmp):
                shutil.rmtree(data_target_tmp)
            shutil.copytree(data_path, data_target_tmp)
            if os.path.isdir(target_data):
                shutil.rmtree(target_data)
            os.replace(data_target_tmp, target_data)
            with open(marker, "w") as f:
                f.write(lib_path)
            log("kokoro",
                f"espeak-ng data path too long for the bundled "
                f"library's internal buffer ({len(data_path)} chars) — "
                f"mirrored to {mirror!r}.", level="warn"
            )

    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    EspeakWrapper.set_library(target_lib)
    EspeakWrapper.set_data_path(target_data)


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
    # Keep paragraph boundaries. KPipeline uses newlines as phrase breaks;
    # flattening all whitespace made multi-line onboarding copy sound like a
    # single run-on sentence with no natural reset between ideas.
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _resample_to_reference_rate(audio_f32):
    """Resample Kokoro's 24 kHz output to the AEC reference sample rate
    (16 kHz). This is an echo reference rather than output audio, so linear
    interpolation is sufficient and avoids making SciPy a hidden runtime
    dependency."""
    import numpy as np

    if audio_f32.size == 0:
        return np.zeros(0, dtype=np.float32)
    if KOKORO_SAMPLE_RATE == REFERENCE_SAMPLE_RATE:
        return audio_f32.astype(np.float32, copy=False)
    n = int(round(audio_f32.size * REFERENCE_SAMPLE_RATE / KOKORO_SAMPLE_RATE))
    positions = np.linspace(0, audio_f32.size - 1, n, dtype=np.float64)
    return np.interp(
        positions, np.arange(audio_f32.size), audio_f32,
    ).astype(np.float32)


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
    """Lazy-loaded Kokoro pipeline with interruptible playback.

    The node serializes speech requests. Warm-up may still overlap the first
    request, so model and player initialization each have their own lock.
    ``stop()`` is intentionally lock-free: a bus callback must be able to
    interrupt the active utterance while ``speak()`` is blocked.
    """

    def __init__(
        self,
        *,
        voice: str = KOKORO_VOICE,
        lang: str = KOKORO_LANG,
        bus: Any = None,
        reference_buffer: FarEndReference | None = None,
        audio_backend: str = "sounddevice",
    ) -> None:
        self.voice = voice
        self.lang = lang
        bundled = os.environ.get("JAEGER_KOKORO_ASSETS", "").strip()
        self._bundled_assets = Path(bundled).expanduser().resolve() if bundled else None
        if self._bundled_assets is not None:
            required = (
                self._bundled_assets / "config.json",
                self._bundled_assets / "kokoro-v1_0.pth",
                self._bundled_assets / "voices",
            )
            if not all(path.exists() for path in required):
                raise FileNotFoundError(
                    f"Incomplete bundled Kokoro assets at {self._bundled_assets}"
                )
        self._pipeline: Any = None
        self._pipeline_lock = threading.Lock()
        self.bus = bus
        # Only used on the no-bus path. With a bus, the audio_io driver
        # writes its own AEC reference from what it actually plays,
        # which is both simpler and more accurate than us guessing.
        self.reference_buffer = reference_buffer
        # With a bus: publish to /act/speaker/pcm and let the audio_io
        # driver own the device. Without one: open the device directly,
        # which is what dev tools and benches do.
        if bus is not None:
            from .bus_player import BusPlayer
            self._PlayerCls = BusPlayer
        else:
            from .persistent_player import PersistentKokoroPlayer
            self._PlayerCls = PersistentKokoroPlayer
        self._player: Any = None
        # Same reason ``_pipeline_lock`` exists, for the other half of
        # warm(): background warm and a real-time speak() both call
        # ``_ensure_player``, and unguarded they open TWO output
        # streams — the loser stays subscribed to /act/speaker/state
        # forever (and on the no-bus path holds a second device).
        self._player_lock = threading.Lock()
        # Operator can override the config-default backend at runtime
        # via ``JAEGER_AUDIO_BACKEND`` for quick A/B testing without
        # editing config.yaml.  Falls through to the config / "sounddevice"
        # default in :meth:`_resolve_backend`.
        self._backend_override = os.environ.get("JAEGER_AUDIO_BACKEND")
        self._cancel = threading.Event()
        self._shutdown = threading.Event()
        self.audio_backend = audio_backend

    @property
    def amplitude(self) -> float:
        """RMS of the current output, or silence before the player opens."""
        return self._player.amplitude if self._player is not None else 0.0

    def _resolve_backend(self) -> str:
        """Pick the audio backend for the persistent player.

        Resolution order: env override → instance config → default
        "sounddevice".  Validated against the supported set; an
        unknown name falls back to "sounddevice" with a warning."""
        candidate = self._backend_override or self.audio_backend or "sounddevice"
        from .persistent_player import PersistentKokoroPlayer
        if candidate not in PersistentKokoroPlayer.SUPPORTED_BACKENDS:
            log("kokoro", f"unknown audio_backend {candidate!r}; "
                f"falling back to 'sounddevice'", level="warn")
            return "sounddevice"
        return candidate

    # ── persistent player lifecycle ───────────────────────────────────
    def _ensure_player(self) -> Any:
        """Open the persistent output stream if it isn't already.
        Idempotent; safe to call from warm() AND from the first speak()
        — including concurrently, which background warm makes routine.
        Double-checked like ``_ensure_pipeline``: the second caller
        waits for the first's open instead of racing it."""
        if self._shutdown.is_set():
            raise RuntimeError("Kokoro engine is shutting down")
        if self._player is not None and self._player.is_open():
            return self._player
        with self._player_lock:
            if self._shutdown.is_set():
                raise RuntimeError("Kokoro engine is shutting down")
            if self._player is not None and self._player.is_open():
                return self._player
            if self.bus is not None:
                # A chassis/app-injected bus is an architectural boundary:
                # this engine publishes PCM and must never resolve or open a
                # local hardware backend. AudioIONode is the sole device
                # owner for the application.
                backend = "bus"
                kwargs = dict(
                    bus=self.bus,
                    backend=backend,
                    samplerate=KOKORO_SAMPLE_RATE,
                    channels=1,
                )
            else:
                # Standalone render/dev use only. Production node factories
                # always inject their app bus above.
                backend = self._resolve_backend()
                kwargs = dict(
                    backend=backend,
                    samplerate=KOKORO_SAMPLE_RATE,
                    channels=1,
                )
            player = self._PlayerCls(**kwargs)
            player.start()
            self._player = player
            log("kokoro", f"persistent output stream open → "
                f"backend={backend!r} device={player.device_index} "
                f"name={player.device_name!r}", level="ok")
            return player

    def shutdown(self) -> None:
        """Release the persistent player.  Called from the TUI's
        ``_shutdown`` so the sounddevice stream closes deterministically
        BEFORE Python's interpreter shutdown starts tearing things
        down (avoids the PortAudio-at-Pa_Terminate segfault that bit
        plain 0.2.6).  Idempotent."""
        self._shutdown.set()
        self._cancel.set()
        with self._player_lock:
            player, self._player = self._player, None
        if player is not None:
            try:
                player.close()
            except Exception:  # noqa: BLE001
                pass

    # ── pipeline lifecycle ────────────────────────────────────────────
    def _ensure_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        # Double-checked locking: background warm (main.py's
        # warm_plugins_async) and a real-time speak() call can both reach
        # here before either has loaded anything. The lock makes the
        # SECOND caller wait for the first's load instead of racing it —
        # never a wedge (the first caller always makes progress), never a
        # duplicate load.
        with self._pipeline_lock:
            if self._pipeline is None:
                import warnings

                # Boot-never-blocks-on-network: decide offline vs. online
                # BEFORE touching kokoro/huggingface_hub at all. See
                # ensure_hf_offline_if_cached()'s docstring.
                if self._bundled_assets is None:
                    ensure_hf_offline_if_cached("hexgrad/Kokoro-82M", self.voice)

                # Kokoro's model build emits noisy torch UserWarnings
                # (LSTM dropout) and FutureWarnings (weight_norm deprecation).
                # They are harmless and not actionable by the user — silence
                # them so a `speak` call doesn't spew a wall of stack-frame
                # text into the TUI.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=UserWarning)
                    warnings.simplefilter("ignore", category=FutureWarning)
                    # Fresh-venv-only native crash fix: espeak-ng's
                    # fixed-size C path buffer breaks on long install
                    # paths. `import kokoro` is what FIRST imports
                    # misaki.espeak (not our own top-level import), and
                    # misaki.espeak's own module-level code re-applies
                    # EspeakWrapper.set_library/set_data_path with the
                    # raw (possibly-too-long) site-packages path — so our
                    # override must run AFTER this import, not before, or
                    # misaki's own call clobbers it. See
                    # ensure_short_espeak_paths()'s docstring for the
                    # full root-cause writeup.
                    from kokoro import KModel, KPipeline
                    ensure_short_espeak_paths()
                    if self._bundled_assets is not None:
                        model = KModel(
                            repo_id="hexgrad/Kokoro-82M",
                            config=str(self._bundled_assets / "config.json"),
                            model=str(self._bundled_assets / "kokoro-v1_0.pth"),
                        )
                        self._pipeline = KPipeline(
                            lang_code=self.lang,
                            repo_id="hexgrad/Kokoro-82M",
                            model=model,
                        )
                    else:
                        self._pipeline = KPipeline(
                            lang_code=self.lang, repo_id="hexgrad/Kokoro-82M",
                        )
        return self._pipeline

    def _pipeline_voice(self) -> str:
        """Resolve a Kokoro voice id to the packaged asset when present."""
        if self._bundled_assets is None or self.voice.endswith(".pt"):
            return self.voice
        bundled = self._bundled_assets / "voices" / f"{self.voice}.pt"
        return str(bundled) if bundled.is_file() else self.voice

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
            for _ in pipe(" ", voice=self._pipeline_voice()):
                break
            load_s = time.perf_counter() - t0
        except Exception as exc:
            return {"warmed": False, "reason": f"pipeline load: {exc}",
                    "load_s": round(load_s, 3),
                    "prime_s": round(prime_s, 3)}

        if self._shutdown.is_set():
            return {"warmed": False, "reason": "shutdown requested",
                    "load_s": round(load_s, 3), "prime_s": 0.0}

        # Stage 2 — open the persistent OutputStream in the clean
        # post-model-load window.  Failure here is non-fatal: speak()
        # will retry on first use (and surface the error in the result
        # dict so the operator sees it).
        player_device: Any = None
        try:
            self._ensure_player()
            player_device = self._player.device_name if self._player else None
        except Exception as exc:  # noqa: BLE001
            log("kokoro", f"persistent player warm failed ({exc}); "
                "will retry on first speak()", level="warn")

        if self._shutdown.is_set():
            return {"warmed": False, "reason": "shutdown requested",
                    "load_s": round(load_s, 3), "prime_s": 0.0}

        # Stage 3 — REAL primer synthesis (PyTorch MPS warm-up).
        try:
            t1 = time.perf_counter()
            primer = "Hello, this is a warm-up pass. One, two, three."
            import numpy as np
            chunks: list[Any] = []
            for r in pipe(primer, voice=self._pipeline_voice()):
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
    def render(self, text: str):
        """Text -> a float32 mono buffer at :data:`KOKORO_SAMPLE_RATE`,
        opening no audio device.  ``None`` for empty input.

        The public face of ``_synthesize``. ``speak`` also plays audio,
        which makes it unsuitable on a machine with no speaker — a build box,
        a container, an SSH session — and unusable for the obvious
        non-talking thing Kokoro is good for: writing a wav.  Markdown
        stripping and SSML are applied exactly as in ``speak``, because
        a rendered file that differed from what you hear would be a
        trap rather than a feature.
        """
        cleaned = clean_for_tts(text)
        if not cleaned:
            return None
        audio, _ = self._synthesize(cleaned)
        return audio

    def _synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: float = 1.0,
        cancel_event: threading.Event | None = None,
    ) -> tuple[Any, bool]:
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
                    for r in pipe(value, voice=voice or self._pipeline_voice(), speed=rate):
                        if cancel_event is not None and cancel_event.is_set():
                            return None, has_ssml
                        if r.audio is not None:
                            chunks.append(np.asarray(r.audio, dtype=np.float32))
                else:
                    n = int(KOKORO_SAMPLE_RATE * value / 1000)
                    if n > 0:
                        chunks.append(np.zeros(n, dtype=np.float32))
        else:
            for r in pipe(text, voice=voice or self._pipeline_voice(), speed=rate):
                if cancel_event is not None and cancel_event.is_set():
                    return None, has_ssml
                if r.audio is not None:
                    chunks.append(np.asarray(r.audio, dtype=np.float32))
        if not chunks:
            return None, has_ssml
        return np.concatenate(chunks), has_ssml

    def speak(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: float = 1.0,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Synthesize speech with Kokoro and play through the persistent
        sounddevice output.  Supports minimal SSML: <speak>,
        <break time="Xms"/>, <breath/>.

        On the direct-device path, streams chunks through the persistent
        player as Kokoro produces them.  On the JaegerOS bus path, renders
        the complete utterance before publishing it.  The audio driver
        cannot distinguish an inter-chunk synthesis pause from the end of
        an utterance, so publishing generator chunks individually can make
        it close a high-latency device before any sound reaches the
        speakers.  Blocks until playback finishes.  Markdown (``**bold**``,
        code fences, link syntax) is stripped before synthesis.

        ``voice`` and ``rate`` are request-local overrides. The configured
        pipeline language remains fixed, so the voice must be compatible
        with that language.
        """
        import numpy as np

        try:
            speed = float(rate)
        except (TypeError, ValueError):
            return {"spoken": False, "reason": "speech rate must be a number"}
        if not 0.5 <= speed <= 2.0:
            return {
                "spoken": False,
                "reason": "speech rate must be between 0.5 and 2.0",
            }

        cleaned = clean_for_tts(text)
        if not cleaned:
            return {"spoken": False, "reason": "empty text"}
        if not 0.5 <= float(rate) <= 2.0:
            return {
                "spoken": False,
                "reason": "rate must be between 0.5 and 2.0",
            }

        # A new event keeps a late stop for one request from cancelling the
        # next request in the node's queue.
        self._cancel = threading.Event()

        started = time.perf_counter()
        try:
            player = self._ensure_player()
            player.begin(correlation_id)
        except Exception as exc:  # noqa: BLE001
            return {
                "spoken": False,
                "reason": f"player open failed: {exc}",
                "text": cleaned,
            }
        try:
            pipe = self._ensure_pipeline()
        except Exception as exc:  # noqa: BLE001
            return {
                "spoken": False,
                "reason": f"pipeline load failed: {exc}",
                "text": cleaned,
            }
        has_ssml = (
            "<break" in cleaned.lower()
            or "<breath" in cleaned.lower()
            or "<speak" in cleaned.lower()
        )

        queued_samples = 0

        def _enqueue_chunk(chunk_24k: np.ndarray) -> None:
            """Queue one chunk and mirror it to direct-path AEC."""
            nonlocal queued_samples
            if chunk_24k.size == 0 or self._cancel.is_set():
                return
            # On the bus path the driver writes its own reference from
            # what it actually plays; writing one here as well would
            # double-count the far end.
            if self.bus is None and self.reference_buffer is not None:
                try:
                    ref = _resample_to_reference_rate(chunk_24k)
                    self.reference_buffer.write(ref)
                except Exception:  # noqa: BLE001 — best effort
                    pass
            player.enqueue(chunk_24k)
            queued_samples += int(chunk_24k.size)

        try:
            if self.bus is not None:
                # A bus AudioOutFrame is an independently deliverable unit;
                # there is currently no separate "more chunks are coming"
                # marker in that contract.  Keep the utterance contiguous so
                # audio_io's empty-source state means the real end, rather
                # than a temporary pause while Kokoro generates its next
                # result.  This also matches the proven JP01/CC01 pipeline.
                rendered, has_ssml = self._synthesize(
                    cleaned,
                    voice=voice,
                    rate=rate,
                    cancel_event=self._cancel,
                )
                if rendered is not None and not self._cancel.is_set():
                    _enqueue_chunk(
                        np.asarray(rendered, dtype=np.float32))
            elif has_ssml:
                for kind, value in _ssml_segments(cleaned):
                    if kind == "text":
                        for r in pipe(
                            value, voice=voice or self._pipeline_voice(), speed=rate,
                        ):
                            if self._cancel.is_set():
                                break
                            if r.audio is None:
                                continue
                            _enqueue_chunk(
                                np.asarray(r.audio, dtype=np.float32))
                    else:  # silence_ms
                        n = int(KOKORO_SAMPLE_RATE * value / 1000)
                        if n > 0:
                            _enqueue_chunk(np.zeros(n, dtype=np.float32))
            else:
                for r in pipe(
                    cleaned, voice=voice or self._pipeline_voice(), speed=rate,
                ):
                    if self._cancel.is_set():
                        break
                    if r.audio is None:
                        continue
                    _enqueue_chunk(np.asarray(r.audio, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            return {
                "spoken": False,
                "reason": f"synthesis failed: {exc}",
                "text": cleaned,
            }

        if self._cancel.is_set():
            return {
                "spoken": False,
                "reason": "interrupted",
                "text": cleaned,
                "samples": queued_samples,
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
                "reason": getattr(player, "last_error", None) or "drain timeout",
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

    def stop(self) -> None:
        """Interrupt synthesis/playback without closing the persistent path.

        Called from the bus delivery thread for barge-in and from node
        shutdown. Setting the event is non-blocking; the active synthesis
        loop observes it between chunks, while the player immediately drops
        audio already queued at the speaker.
        """
        self._cancel.set()
        player = self._player
        if player is not None:
            try:
                player.cancel()
            except Exception:  # noqa: BLE001
                pass
        if self.reference_buffer is not None:
            self.reference_buffer.clear()
