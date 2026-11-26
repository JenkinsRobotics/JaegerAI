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
import platform
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

import logging as _logging

_LOGGER = _logging.getLogger("jaeger_kokoro_tts")


def log(component: str, message: str, *, level: str = "info") -> None:
    fn = getattr(_LOGGER, level if level in ("debug", "info", "warning", "error") else ("warning" if level == "warn" else "info"))
    fn("[%s] %s", component, message)


FarEndReference = Any


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
#: The same Kokoro weights converted for Apple's MLX, which runs them on
#: the GPU. Measured on an M1 Max, 8.6 s of speech: 0.39 s on MLX against
#: 1.3-2.3 s for PyTorch on the CPU (PyTorch does not pick the Apple GPU
#: by itself, and when told to, its first sentence takes 11 s).
KOKORO_MLX_REPO = "mlx-community/Kokoro-82M-bf16"
_APPLE_SILICON = sys.platform == "darwin" and platform.machine() == "arm64"
_KOKORO_MODEL_FILENAMES = {
    KOKORO_MLX_REPO: "kokoro-v1_0.safetensors",
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
        f"voices/{voice}.{'safetensors' if repo_id == KOKORO_MLX_REPO else 'pt'}",
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
class _MlxResult:
    """One synthesised chunk, shaped like kokoro's: ``.audio`` is float32.
    ``marks`` are its lip marks (see :func:`lip_marks`)."""
    __slots__ = ("audio", "marks")

    def __init__(self, audio: Any, marks: list | None = None) -> None:
        self.audio = audio
        self.marks = marks or []


# Sounds the lips make that audio alone cannot tell from n/t/s: m/b/p press
# the lips shut ("p"), f/v tuck the lower lip under the teeth ("f").
_LIPS = {"p": "p", "b": "p", "m": "p", "f": "f", "v": "f"}
_FRAME_S = 0.025     # one Kokoro duration frame


def lip_marks(phonemes: str, frames: list, vocab: dict) -> list:
    """``[start, end, kind]`` in seconds from the chunk's start for each lip
    closure, from Kokoro's own phoneme lengths (``frames``: <bos> first, one
    per phoneme, <eos> last).

    Moved here from Jaeger Avatar, where it was checked by ear and level on
    "Mom bought a big puppy": each b/p's silent closure falls inside its
    mark. The model skips phonemes it has no id for, so they are skipped
    here too, keeping each length on its own sound.
    """
    marks = []
    t = max(0, frames[0] - 3) * _FRAME_S   # the sound runs 3 frames ahead of <bos>
    for ph, n in zip([p for p in phonemes if p in vocab], frames[1:-1]):
        if ph in _LIPS:
            marks.append([round(t, 3), round(t + n * _FRAME_S, 3), _LIPS[ph]])
        t += n * _FRAME_S
    return marks


def _marks_of(result: Any, vocab: dict | None) -> list:
    """A result's lip marks: its own, or made from its phoneme timings."""
    marks = getattr(result, "marks", None)
    if marks is not None:
        return list(marks)
    lengths = getattr(result, "pred_dur", None)
    phonemes = getattr(result, "phonemes", None)
    if lengths is None or not phonemes or not vocab:
        return []
    return lip_marks(phonemes, [int(n) for n in lengths.tolist()], vocab)


# Kokoro pads every clip with dead air (measured 2026-11-11 in Jaeger Avatar:
# 0.28-0.43 s before the voice, 0.49 s after). Seconds of it kept before and
# after the voice — the values Jaeger Avatar's own voice code was tuned to by
# ear. A speaker that swallows its first milliseconds wants more lead: set
# ``KokoroTTS.trim`` on that robot; ``None`` leaves Kokoro's padding alone.
TRIM = (0.012, 0.09)
_FADE_S = 0.006      # a cut edge ramps over this long, so it does not click


def _trimmed(audio: Any, marks: list, trim: tuple | None) -> tuple[Any, list]:
    """``audio`` without the dead air around the voice, and ``marks`` moved
    to match. Sound that is voice from edge to edge, or has no voice at
    all, comes back as it was."""
    if trim is None or not len(audio):
        return audio, marks
    level = np.abs(audio)
    loud = np.nonzero(level > max(0.012, float(level.max()) * 0.03))[0]
    if not len(loud):
        return audio, marks
    rate = KOKORO_SAMPLE_RATE
    start = max(0, int(loud[0]) - int(rate * trim[0]))
    end = min(len(audio), int(loud[-1]) + 1 + int(rate * trim[1]))
    if start == 0 and end == len(audio):
        return audio, marks
    audio = np.array(audio[start:end], dtype=np.float32)
    fade = min(int(rate * _FADE_S), len(audio) // 2)
    if fade and start:
        audio[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    if fade and end < len(level):
        audio[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    cut = start / rate
    return audio, [[round(max(0.0, a - cut), 3), round(b - cut, 3), kind]
                   for a, b, kind in marks if b - cut > 0]


class SpeechChunk(np.ndarray):
    """One chunk of speech: float32 mono sound, plus ``marks`` — its lip
    marks, ``[start, end, "p" | "f"]`` in seconds from the chunk's start.

    ponytail: an ndarray with one extra field, so every caller that only
    wants sound keeps working unchanged. A copy or a slice has no marks
    (they were timed for the whole chunk). A plain (sound, marks) pair if
    a caller ever needs to serialise chunks.
    """
    marks: list = []

    @classmethod
    def of(cls, audio: Any, marks: list | None = None) -> "SpeechChunk":
        chunk = np.asarray(audio, dtype=np.float32).reshape(-1).view(cls)
        chunk.marks = list(marks or [])
        return chunk


class _MlxPipeline:
    """Kokoro on the Apple GPU, called exactly like kokoro's ``KPipeline``
    so the rest of the engine cannot tell which one it has."""

    def __init__(self, lang: str) -> None:
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model
        # A small buffer cache roughly halves the time per line (measured
        # in Jaeger Avatar, which runs the same model the same way).
        mx.set_cache_limit(128 * 1024 * 1024)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):   # it print()s on load
            self._model = load_model(KOKORO_MLX_REPO)
            self._pipe = self._model._get_pipeline(lang)
        self._lang, self._vocab = lang, self._model.vocab
        # ponytail: one render at a time. Two threads rendering at once
        # worked when tried, but MLX does not promise it; drop the lock
        # only if overlapping voices are ever wanted.
        self._lock = threading.Lock()

    def _pipe_for(self, voice: str):
        # A Kokoro voice's first letter is its language. A British voice asked
        # for on an American pipeline is read with British rules (the model
        # keeps one pipeline per language).
        # ponytail: American and British only, the two Jaeger Avatar offers;
        # any other voice is read with the language the engine was opened in.
        lang = voice[:1]
        if lang == self._lang or lang not in ("a", "b"):
            return self._pipe
        return self._model._get_pipeline(lang)

    def __call__(self, text: str, *, voice: str, speed: float = 1.0):
        with self._lock:
            for r in self._pipe_for(voice)(text, voice=voice, speed=speed):
                if r.audio is not None:
                    yield _MlxResult(
                        np.array(r.audio, dtype=np.float32).reshape(-1),
                        _marks_of(r, self._vocab))


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
        self.trim: tuple[float, float] | None = TRIM   # dead air kept around the voice; see TRIM
        self._pipeline: Any = None
        #: What Kokoro runs on, once loaded: "mlx" (Apple GPU), "cuda" or
        #: "cpu". Not called ``backend``: on the players that word means
        #: the audio output.
        self.compute = ""
        self.sample_rate = KOKORO_SAMPLE_RATE
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

                # The Apple GPU first, on Apple Silicon only: anywhere else
                # MLX is not installable and PyTorch (CUDA, else the CPU)
                # is the fast path. JAEGER_KOKORO_BACKEND=torch forces
                # the PyTorch path (to compare voices, or if MLX misbehaves);
                # =mlx makes a failed MLX load an error instead of a fallback.
                want = os.environ.get("JAEGER_KOKORO_BACKEND", "auto").lower()
                if want == "mlx" or (want == "auto" and _APPLE_SILICON):
                    set_offline = "HF_HUB_OFFLINE" not in os.environ
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            import mlx_audio  # noqa: F401 — absent off Apple Silicon
                            ensure_hf_offline_if_cached(KOKORO_MLX_REPO, self.voice)
                            # Same espeak path fix as below, and the same
                            # ordering: after misaki.espeak is imported.
                            import misaki.espeak  # noqa: F401
                            ensure_short_espeak_paths()
                            self._pipeline = _MlxPipeline(self.lang)
                        self.compute = "mlx"
                        log("kokoro", "Kokoro on the Apple GPU (MLX).")
                        return self._pipeline
                    except Exception as exc:  # noqa: BLE001
                        if want == "mlx":
                            raise
                        if set_offline:   # do not leave PyTorch unable to download
                            os.environ.pop("HF_HUB_OFFLINE", None)
                            try:
                                import huggingface_hub.constants as _c
                                _c.HF_HUB_OFFLINE = False
                            except Exception:  # noqa: BLE001
                                pass
                        log("kokoro", f"MLX not usable ({type(exc).__name__}: "
                            f"{exc}); using PyTorch, which is 3-4x slower on "
                            "a Mac. `pip install mlx-audio` restores the GPU "
                            "path.", level="warn")

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
                    from kokoro import KPipeline
                    ensure_short_espeak_paths()
                    if self._bundled_assets is not None:
                        from kokoro import KModel
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
                    try:
                        self.compute = next(
                            self._pipeline.model.parameters()).device.type
                    except Exception:  # noqa: BLE001 — a report, never a blocker
                        self.compute = "cpu"
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
            "compute": self.compute,
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

    def synth(self, text: str, *, voice: str | None = None, rate: float = 1.0):
        """Text -> float32 mono chunks at :attr:`sample_rate`, each handed
        over as soon as it is rendered, opening no audio device.

        For a caller that plays (or streams, or lip-syncs) the audio
        itself. Same clean-up and SSML as ``render`` and ``speak``.
        ``voice`` and ``rate`` are for this line only. Each chunk is a
        :class:`SpeechChunk`: its ``marks`` say when the lips close (m/b/p)
        or tuck (f/v), for whoever moves a mouth."""
        cleaned = clean_for_tts(text)
        if cleaned:
            yield from self._chunks(cleaned, voice=voice, rate=rate)

    def _chunks(self, text: str, *, voice: str | None = None, rate: float = 1.0):
        import numpy as np

        pipe = self._ensure_pipeline()
        vocab = getattr(getattr(pipe, "model", None), "vocab", None)
        low = text.lower()
        ssml = "<break" in low or "<breath" in low or "<speak" in low
        for kind, value in (_ssml_segments(text) if ssml else [("text", text)]):
            if kind == "text":
                for r in pipe(value, voice=voice or self._pipeline_voice(), speed=rate):
                    if r.audio is not None:
                        yield SpeechChunk.of(*_trimmed(
                            np.asarray(r.audio, dtype=np.float32).reshape(-1),
                            _marks_of(r, vocab), self.trim))
            else:
                n = int(KOKORO_SAMPLE_RATE * value / 1000)
                if n > 0:
                    yield SpeechChunk.of(np.zeros(n, dtype=np.float32))

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

        low = text.lower()
        has_ssml = "<break" in low or "<breath" in low or "<speak" in low
        chunks: list[Any] = []
        for chunk in self._chunks(text, voice=voice, rate=rate):
            if cancel_event is not None and cancel_event.is_set():
                return None, has_ssml
            chunks.append(chunk)
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
        cancel_event: threading.Event | None = None,
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
        with that language. ``cancel_event`` is an optional request-owned
        token; an already-set token prevents player/model startup.
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

        # The node creates this token before entering the engine. Adopting it
        # preserves Stop during that handoff; never clear/replace a supplied
        # event. Standalone calls still receive a fresh request-local token.
        cancellation = cancel_event if cancel_event is not None else threading.Event()
        self._cancel = cancellation
        if cancellation.is_set():
            return {"spoken": False, "reason": "interrupted", "text": cleaned, "samples": 0}

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
        if cancellation.is_set():
            return {"spoken": False, "reason": "interrupted", "text": cleaned, "samples": 0}
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
            if chunk_24k.size == 0 or cancellation.is_set():
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
                    cancel_event=cancellation,
                )
                if rendered is not None and not cancellation.is_set():
                    _enqueue_chunk(
                        np.asarray(rendered, dtype=np.float32))
            else:
                # The same chunks ``synth`` and ``render`` give, played as
                # each one is ready: what is heard is what would be written.
                for chunk in self._chunks(cleaned, voice=voice, rate=rate):
                    if cancellation.is_set():
                        break
                    _enqueue_chunk(np.asarray(chunk, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            return {
                "spoken": False,
                "reason": f"synthesis failed: {exc}",
                "text": cleaned,
            }

        if cancellation.is_set():
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
        drained = player.wait_until_drained()
        # cancel() may unblock drain with True (or False). Drain completion
        # alone is not evidence that an interrupted utterance played fully.
        if cancellation.is_set():
            return {
                "spoken": False,
                "reason": "interrupted",
                "text": cleaned,
                "samples": queued_samples,
            }
        if not drained:
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
