"""Shared realtime voice audio session.

``AudioSession`` is the library-layer owner for mic/STT coordination:
AEC setup, Whisper adapter construction, pause/follow-up/drain control,
non-speech filtering, and optional self-speech rejection.  It is not a
node by itself; ``AudioSessionNode`` wraps it for bus publication.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from jaeger_os.core.voice import is_non_speech_marker


class STTAdapter(Protocol):
    """The STT-shaped surface used by the audio session."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def next_phrase(self, timeout: float | None = 1.0) -> str | None: ...
    def set_paused(self, paused: bool) -> None: ...
    def set_on_speech_detected(self, callback: Callable[[], None] | None) -> None: ...
    def open_followup(self) -> None: ...
    def drain_pending(self) -> None: ...


@dataclass(frozen=True)
class AudioSessionConfig:
    """Construction settings for a realtime voice session."""

    stt_mode: str = "two_pass"
    fast_model_name: str = "base.en"
    accurate_model_name: str = "medium.en"
    language: str = "en"
    require_wake_word: bool = False
    wake_phrases: tuple[str, ...] = ()
    followup_window_s: float = 10.0
    wake_match_threshold: float = 0.78
    # WebRTC-VAD phrase segmentation (vad_segment and two_pass).
    vad_aggressiveness: int = 2
    pre_roll_ms: int = 240
    post_padding_ms: int = 250
    silence_hangover_ms: int = 700
    min_speech_ms: int = 400
    max_speech_ms: int = 8000
    barge_in_ms: int = 200
    short_phrase_max_ms: int = 1500
    short_phrase_hangover_ms: int = 350
    # Energy-segmented phrase pipelines (continuous and phrase_word).
    continuous_phrase_timeout_s: float = 1.0
    continuous_max_phrase_s: float = 8.0
    continuous_transcribe_every_s: float = 0.6
    continuous_min_transcribe_s: float = 0.4
    continuous_energy_threshold: float = 0.005
    # Rolling caption pipelines (window and local_agreement).
    stream_window_s: float = 7.0
    stream_transcribe_every_s: float = 1.2
    stream_min_transcribe_s: float = 1.0
    stream_energy_threshold: float = 0.008
    stream_min_commit_words: int = 1
    stream_min_overlap_words: int = 2
    stream_max_commit_words: int = 28
    stream_resync_after_passes: int = 4
    # Bounded realtime queues. Newest input/output wins under overload.
    mic_queue_max_frames: int = 200
    output_queue_max_phrases: int = 16
    barge_in: bool = False
    audio_backend: str = "sounddevice"
    self_speech_filter: bool = True
    self_speech_threshold: float = 0.75
    # LLM gate (operator-locked 2026-06-07): the node owns its
    # full domain.  AudioSession runs an LLM-based <ignore>/<reply>
    # classification AFTER deterministic filters; only confirmed
    # messages are published to /sense/stt/transcript.  The brain agent
    # never sees raw noise.
    llm_gate: bool = True
    # Max tokens the gate LLM call generates — only need enough for
    # "<ignore>" or "<reply>" plus a few padding chars.
    llm_gate_max_tokens: int = 10

    def __post_init__(self) -> None:
        """Reject unsafe realtime settings before model or hardware startup."""
        if not 0.0 <= self.wake_match_threshold <= 1.0:
            raise ValueError("wake_match_threshold must be between 0 and 1")
        if self.vad_aggressiveness not in (0, 1, 2, 3):
            raise ValueError("vad_aggressiveness must be 0, 1, 2, or 3")
        nonnegative_ms = {
            "pre_roll_ms": self.pre_roll_ms,
            "post_padding_ms": self.post_padding_ms,
            "short_phrase_max_ms": self.short_phrase_max_ms,
        }
        positive_ms = {
            "silence_hangover_ms": self.silence_hangover_ms,
            "min_speech_ms": self.min_speech_ms,
            "max_speech_ms": self.max_speech_ms,
            "barge_in_ms": self.barge_in_ms,
            "short_phrase_hangover_ms": self.short_phrase_hangover_ms,
        }
        for name, value in nonnegative_ms.items():
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        for name, value in positive_ms.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_speech_ms < self.min_speech_ms:
            raise ValueError("max_speech_ms must be >= min_speech_ms")

        positive_intervals = {
            "continuous_phrase_timeout_s": self.continuous_phrase_timeout_s,
            "continuous_max_phrase_s": self.continuous_max_phrase_s,
            "continuous_transcribe_every_s": self.continuous_transcribe_every_s,
            "continuous_min_transcribe_s": self.continuous_min_transcribe_s,
            "stream_window_s": self.stream_window_s,
            "stream_transcribe_every_s": self.stream_transcribe_every_s,
            "stream_min_transcribe_s": self.stream_min_transcribe_s,
        }
        for name, value in positive_intervals.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        for name, value in {
            "continuous_energy_threshold": self.continuous_energy_threshold,
            "stream_energy_threshold": self.stream_energy_threshold,
        }.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        positive_counts = {
            "stream_min_commit_words": self.stream_min_commit_words,
            "stream_min_overlap_words": self.stream_min_overlap_words,
            "stream_max_commit_words": self.stream_max_commit_words,
            "stream_resync_after_passes": self.stream_resync_after_passes,
            "mic_queue_max_frames": self.mic_queue_max_frames,
            "output_queue_max_phrases": self.output_queue_max_phrases,
        }
        for name, value in positive_counts.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.stream_max_commit_words < self.stream_min_commit_words:
            raise ValueError(
                "stream_max_commit_words must be >= stream_min_commit_words"
            )


@dataclass(frozen=True)
class GateDecision:
    """Per-phrase decision the node logs to its activity stream."""

    accepted: bool
    text: str
    reason: str  # accepted | non_speech | self_speech | llm_ignore |
                 # llm_error | no_client | empty


class AudioSession:
    """Own STT state for one realtime voice session.

    It no longer owns the mic or the echo canceller.
    :mod:`jaeger_os.nodes.audio_io` owns both and publishes cleaned
    frames on ``/sense/mic/pcm``; this session's adapter subscribes.

    That deletes a seam rather than moving it. There used to be a
    far-end reference threaded from whichever TTS module was installed,
    through ``nodes/runtime.py``, into this session, into the STT
    adapter, into the mic callback — so that AEC could subtract the
    AI's own voice. All of it existed because two modules each owned
    half of one device pair. One driver owning both makes the whole
    chain unnecessary: the reference never leaves the node that has
    both signals.
    """

    def __init__(
        self,
        *,
        adapter: STTAdapter,

        barge_in_live: bool = False,
        self_speech_filter: bool = True,
        self_speech_threshold: float = 0.75,
        llm_gate: bool = True,
        llm_client: Any = None,
        llm_lock: Any = None,
        llm_gate_max_tokens: int = 10,
        followup_window_s: float = 10.0,
    ) -> None:
        self.adapter = adapter
        self.barge_in_live = barge_in_live
        self.self_speech_filter = self_speech_filter
        self.self_speech_threshold = self_speech_threshold
        self.last_reply_text = ""
        # LLM gate (node-owned, operator-locked 2026-06-07):
        # AudioSession owns the full input pipeline; the brain only
        # sees confirmed messages.  ``llm_client`` is the brain's
        # llama-cpp / mlx-lm client shared via the runtime singleton;
        # ``llm_lock`` serialises the gate call against the brain's
        # turn-generation so two threads don't drive the same model.
        self.llm_gate = llm_gate
        self.llm_client = llm_client
        self.llm_lock = llm_lock
        self.llm_gate_max_tokens = llm_gate_max_tokens
        self.followup_window_s = followup_window_s
        self._followup_open_until: float = 0.0
        # Optional callback the node registers to surface gate
        # decisions in its activity stream (the TUI logs these as
        # 🤫 ignored / 🎙 accepted lines).
        self._on_gate_decision: Callable[[GateDecision], None] | None = None

    @classmethod
    def build(
        cls,
        config: AudioSessionConfig,
        *,
        bus: Any = None,
        llm_client: Any = None,
        llm_lock: Any = None,
    ) -> "AudioSession":
        """Build the production Whisper-backed audio session.

        ``bus`` is where mic frames come from. It replaces the
        ``far_end`` reference this used to take: the STT adapter
        subscribes to ``/sense/mic/pcm`` rather than opening a device,
        and echo cancellation has already happened upstream in
        :mod:`jaeger_os.nodes.audio_io`.

        ``llm_client`` + ``llm_lock`` enable the in-node LLM gate.
        The runtime singleton wires the brain's client through when
        ``ensure_audio_session_node`` runs after the brain has loaded.
        With ``llm_client=None`` the gate degrades to deterministic-
        filters-only (still safer than no gate at all)."""
        # AEC lives in jaeger_os.nodes.audio_io now, with the devices.
        # This session no longer builds one, owns a reference buffer, or
        # knows whether cancellation is running — it receives frames
        # that are already clean.
        #
        # `barge_in_live` therefore reflects what the OPERATOR asked
        # for, not what the canceller achieved; the driver's health()
        # reports the authoritative AEC state. When barge-in is on and
        # the driver has no AEC, self-speech filtering (on by default,
        # `config.self_speech_filter`) is the backstop that keeps the
        # agent from answering itself.
        adapter = cls._build_adapter(config, bus=bus)
        return cls(
            adapter=adapter,
            barge_in_live=bool(config.barge_in),
            self_speech_filter=config.self_speech_filter,
            self_speech_threshold=config.self_speech_threshold,
            llm_gate=config.llm_gate,
            llm_client=llm_client,
            llm_lock=llm_lock,
            llm_gate_max_tokens=config.llm_gate_max_tokens,
            followup_window_s=config.followup_window_s,
        )

    @staticmethod
    def _build_adapter(
        config: AudioSessionConfig,
        *,
        bus: Any,
    ) -> STTAdapter:
        wake_phrases = config.wake_phrases or _default_wake_phrases()
        # The STT method registry is the single swap point — flip variants
        # by name via config.stt_mode. Unknown names fail startup loudly;
        # silently choosing two_pass would run the wrong memory/latency profile.
        # 0.9 step 4 split: whisper_stt is its own installed package
        # (jaeger_whisper_stt) — resolved via discover_modules() instead
        # of a hardcoded dotted import (same reasoning as
        # nodes/runtime.py's engine-symbol guards).
        from jaeger_os.core.modules import resolve_slot_module
        registry = resolve_slot_module("stt", "engine.registry")
        if registry is None:
            raise RuntimeError(
                "AudioSession._build_adapter: no stt-slot module installed"
            )
        get = registry.get

        method = get(config.stt_mode)
        if config.require_wake_word and not getattr(method, "wake_word", True):
            raise ValueError(
                f"STT method {config.stt_mode!r} cannot apply engine wake-word "
                "gating because it commits rolling word/window chunks; use "
                "two_pass or phrase_word, or detect directed commands in the app"
            )
        return method.make(config, bus, wake_phrases)

    def start(self) -> None:
        self.adapter.start()

    def stop(self) -> None:
        self.adapter.stop()

    @property
    def last_phrase_timing(self) -> dict[str, float]:
        """Speech-side timing of the most recent committed phrase
        (``speech_end`` / ``stt_done`` perf_counter stamps), read from
        the STT adapter. Empty when the adapter doesn't report timing
        (continuous mode, test stubs)."""
        return dict(getattr(self.adapter, "last_phrase_timing", {}) or {})

    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Return the next user phrase that passes deterministic
        filters, or ``None`` if nothing useful is ready.

        Deterministic input pipeline (operator-locked 2026-06-07,
        perf-corrected 2026-06-07 after KV-cache thrashing bench
        — see ``dev/benchmark/voice_gate_latency.py``):
          1. STT adapter polls the mic + finalises a phrase
          2. Non-speech marker filter ([BLANK_AUDIO] / (beeping) etc.)
          3. Self-speech filter (mic picked up our own reply)

        The LLM `<ignore>`/`<reply>` gate runs INSIDE the brain's
        normal turn — it's the prefix of the response, single-pass.
        Trying to run it as a separate gate call from this node
        invalidated the brain's prefill KV cache and tanked voice
        latency 50× in real-world testing (a clean 0.39s brain
        turn ballooned to 19.79s).  The node owns its DETERMINISTIC
        filters; the brain owns the SEMANTIC gate via its own
        system prompt.  See ``core/prompts/assemble.py``."""
        phrase = self.adapter.next_phrase(timeout=timeout)
        text = (phrase or "").strip()
        if not text:
            return None
        if is_non_speech_marker(text):
            self._emit_decision(GateDecision(
                accepted=False, text=text, reason="non_speech",
            ))
            return None
        if self._is_self_speech(text):
            self._emit_decision(GateDecision(
                accepted=False, text=text, reason="self_speech",
            ))
            return None
        # Phrase passes deterministic filters — emit an "accepted"
        # decision for the audit trail and hand off to the brain.
        # The brain's response prefix is the semantic gate (see
        # VOICE_LLM_GATE_RULE in core/prompts/rules.py).
        self._emit_decision(GateDecision(
            accepted=True, text=text, reason="deterministic_pass",
        ))
        return text

    def set_paused(self, paused: bool) -> None:
        self.adapter.set_paused(paused)

    def set_on_speech_detected(
        self,
        callback: Callable[[], None] | None,
    ) -> None:
        self.adapter.set_on_speech_detected(callback)

    def set_on_gate_decision(
        self,
        callback: "Callable[[GateDecision], None] | None",
    ) -> None:
        """Register a callback the node uses to log gate decisions
        (🤫 ignored / 🎙 accepted lines in the activity stream).
        Callback runs on the polling thread; must not block."""
        self._on_gate_decision = callback

    def open_followup(self) -> None:
        """Open the follow-up window.  Tracks the timestamp so the
        LLM gate's addressed_hint clause activates."""
        import time as _time
        self._followup_open_until = _time.time() + self.followup_window_s
        self.adapter.open_followup()

    def in_followup_window(self) -> bool:
        """Are we inside the post-reply follow-up window right now?
        Used by the LLM gate to switch from strict default-ignore to
        permissive default-reply."""
        import time as _time
        return _time.time() < self._followup_open_until

    def drain_pending(self) -> None:
        self.adapter.drain_pending()

    def remember_reply(self, text: str) -> None:
        self.last_reply_text = (text or "").strip()

    def clear_reference_buffer(self) -> None:
        """Kept as a no-op: the reference buffer moved into the audio
        driver, which manages its own lifetime. Callers that used to
        clear it around a pause boundary have nothing to clear."""
        return None

    def _is_self_speech(self, text: str) -> bool:
        if not self.self_speech_filter or not self.last_reply_text:
            return False
        ratio = difflib.SequenceMatcher(
            None,
            text.lower(),
            self.last_reply_text.lower(),
        ).ratio()
        return ratio >= self.self_speech_threshold

    # ── LLM gate REMOVED 2026-06-07 ────────────────────────────────
    # Two prompts thrashed the brain's single KV-cache slot — a
    # gate call with VOICE_LLM_GATE_RULE invalidated the brain's
    # 14K-token prefill, forcing a cold prefill on the next brain
    # turn.  Measured 50× slowdown in dev/benchmark/voice_gate_latency.py.
    #
    # The LLM gate now lives in the brain's normal turn as the
    # response prefix (VoiceLLM single-pass model).  AudioSession
    # owns the FAST deterministic filters (non_speech_marker,
    # self_speech).  The brain owns the SEMANTIC gate via
    # VOICE_LLM_GATE_RULE in its system prompt.
    #
    # The llm_client / llm_lock / llm_gate fields and the
    # in_followup_window() method are KEPT in the constructor for
    # backward-compat with callers + tests + the runtime factory.
    # They're inert now; future 0.5 streaming-mode work might use
    # them.

    def _emit_decision(self, decision: GateDecision) -> None:
        """Surface a gate decision to the registered callback, if any.
        Safe to call regardless of whether a callback is wired."""
        callback = self._on_gate_decision
        if callback is None:
            return
        try:
            callback(decision)
        except Exception:  # noqa: BLE001
            # A logging callback must never break the audio loop.
            pass


def _default_wake_phrases() -> tuple[str, ...]:
    # 0.9 step 4 split: same discovery-driven resolution as
    # _build_adapter above — whisper_stt is its own installed package.
    from jaeger_os.core.modules import resolve_slot_module
    base = resolve_slot_module("stt", "engine._base")
    if base is None:
        return ()
    return base.DEFAULT_WAKE_PHRASES
