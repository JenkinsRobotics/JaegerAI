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
    require_wake_word: bool = False
    wake_phrases: tuple[str, ...] = ()
    followup_window_s: float = 10.0
    barge_in: bool = False
    audio_backend: str = "sounddevice"
    self_speech_filter: bool = True
    self_speech_threshold: float = 0.75
    # LLM gate (operator-locked 2026-06-07): the node owns its
    # full domain.  AudioSession runs an LLM-based <ignore>/<reply>
    # classification AFTER deterministic filters; only confirmed
    # messages are published to /sense/transcript.  The brain agent
    # never sees raw noise.
    llm_gate: bool = True
    # Max tokens the gate LLM call generates — only need enough for
    # "<ignore>" or "<reply>" plus a few padding chars.
    llm_gate_max_tokens: int = 10


@dataclass(frozen=True)
class GateDecision:
    """Per-phrase decision the node logs to its activity stream."""

    accepted: bool
    text: str
    reason: str  # accepted | non_speech | self_speech | llm_ignore |
                 # llm_error | no_client | empty


class AudioSession:
    """Own mic/AEC/STT state for one realtime voice session.

    In monolithic mode this session deliberately shares the TTS
    synthesizer's ``reference_buffer`` object in-process so AEC can stay
    aligned without streaming raw speaker audio through the bus.  That is
    a known monolithic-only coupling; the multiprocess path should replace
    it with a dedicated TTS reference topic when raw audio needs to cross
    a process boundary.
    """

    def __init__(
        self,
        *,
        adapter: STTAdapter,
        aec: Any = None,
        reference_buffer: Any = None,
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
        self.aec = aec
        self.reference_buffer = reference_buffer
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
        tts_synth: Any = None,
        llm_client: Any = None,
        llm_lock: Any = None,
    ) -> "AudioSession":
        """Build the production Whisper-backed audio session.

        ``llm_client`` + ``llm_lock`` enable the in-node LLM gate.
        The runtime singleton wires the brain's client through when
        ``ensure_audio_session_node`` runs after the brain has loaded.
        With ``llm_client=None`` the gate degrades to deterministic-
        filters-only (still safer than no gate at all)."""
        aec = None
        reference_buffer = None
        barge_in_live = False
        if config.barge_in:
            try:
                from jaeger_os.core.audio import (
                    AECWrapper,
                    ReferenceBuffer,
                    aec_available,
                )

                if aec_available():
                    aec = AECWrapper(sample_rate=16000, frame_ms=10, enabled=True)
                    reference_buffer = getattr(tts_synth, "reference_buffer", None)
                    if reference_buffer is None:
                        reference_buffer = ReferenceBuffer(
                            sample_rate=16000,
                            capacity_seconds=2.0,
                        )
                        if tts_synth is not None:
                            tts_synth.reference_buffer = reference_buffer
                    barge_in_live = True
            except Exception:  # noqa: BLE001
                aec = None
                reference_buffer = None
                barge_in_live = False

        adapter = cls._build_adapter(config, aec=aec, reference_buffer=reference_buffer)
        return cls(
            adapter=adapter,
            aec=aec,
            reference_buffer=reference_buffer,
            barge_in_live=barge_in_live,
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
        aec: Any,
        reference_buffer: Any,
    ) -> STTAdapter:
        wake_phrases = config.wake_phrases or _default_wake_phrases()
        if config.stt_mode == "continuous":
            from jaeger_os.plugins.whisper_stt import WhisperSTTContinuous

            return WhisperSTTContinuous(
                model_name=config.fast_model_name,
                require_wake_word=config.require_wake_word,
                wake_phrases=wake_phrases,
                followup_window_s=config.followup_window_s,
                aec=aec,
                far_end_buffer=reference_buffer,
                audio_backend=config.audio_backend,
            )
        from jaeger_os.plugins.whisper_stt import WhisperSTTTwoPass

        return WhisperSTTTwoPass(
            fast_model_name=config.fast_model_name,
            accurate_model_name=config.accurate_model_name,
            require_wake_word=config.require_wake_word,
            wake_phrases=wake_phrases,
            followup_window_s=config.followup_window_s,
            aec=aec,
            far_end_buffer=reference_buffer,
            audio_backend=config.audio_backend,
        )

    def start(self) -> None:
        self.adapter.start()

    def stop(self) -> None:
        self.adapter.stop()

    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Return the next CONFIRMED user phrase, or ``None`` if
        nothing real is ready within ``timeout``.

        Full input pipeline (operator-locked 2026-06-07 — the node
        owns its domain):
          1. STT adapter polls the mic + finalises a phrase
          2. Non-speech marker filter ([BLANK_AUDIO] / (beeping) etc.)
          3. Self-speech filter (mic picked up our own reply)
          4. LLM gate (<ignore>/<reply> semantic check via brain's
             llama-cpp client — uses the active-followup hint when
             we're inside the post-reply window)

        Only phrases that pass ALL FOUR layers are returned.  The
        brain agent never sees rejected input, so it cannot fire on
        random TV / movie / ambient noise.  The legacy behaviour of
        passing junk through and parsing <ignore>/<reply> out of the
        brain's response is gone — that's why the brain's system
        prompt no longer carries VOICE_LLM_GATE_RULE.
        """
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
        # Final layer: the LLM gate.  Runs the brain's client with a
        # small max_tokens budget; returns accept/reject + reason.
        decision = self._classify_phrase_llm(text)
        self._emit_decision(decision)
        if not decision.accepted:
            return None
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
        if self.reference_buffer is not None:
            try:
                self.reference_buffer.clear()
            except Exception:  # noqa: BLE001
                pass

    def _is_self_speech(self, text: str) -> bool:
        if not self.self_speech_filter or not self.last_reply_text:
            return False
        ratio = difflib.SequenceMatcher(
            None,
            text.lower(),
            self.last_reply_text.lower(),
        ).ratio()
        return ratio >= self.self_speech_threshold

    # ── LLM gate ────────────────────────────────────────────────────

    def _classify_phrase_llm(self, text: str) -> GateDecision:
        """Run the LLM <ignore>/<reply> gate.

        Uses the brain's llama-cpp / mlx-lm client (shared via the
        runtime singleton) under llm_lock so the gate call doesn't
        race the brain's turn generation.  Returns a GateDecision
        with reason 'llm_ignore' / 'llm_reply' / 'no_client' /
        'llm_error:<Type>' (degrades gracefully when client missing
        or call fails — accept on uncertainty rather than swallow a
        possibly-legitimate reply)."""
        if not self.llm_gate:
            return GateDecision(accepted=True, text=text, reason="gate_off")
        if self.llm_client is None or not hasattr(self.llm_client, "chat"):
            return GateDecision(
                accepted=True, text=text, reason="no_client",
            )
        # Build the gate prompt — voice gate rule, optionally augmented
        # with the addressed_hint clause when we're inside the
        # follow-up window after a recent reply.
        from jaeger_os.core.prompts.rules import (
            VOICE_LLM_GATE_RULE,
            VOICE_FOLLOWUP_HINT_RULE,
        )
        from jaeger_os.core.voice.llm_gate import parse_gate
        prompt = VOICE_LLM_GATE_RULE.strip()
        if self.in_followup_window():
            prompt = prompt + "\n\n" + VOICE_FOLLOWUP_HINT_RULE.strip()
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]
        # Serialise the call against the brain's turn generation —
        # the same lock the brain's agent loop uses.  Worst case the
        # gate waits for an in-flight brain turn to finish; bounded
        # by the brain's stall_timeout.
        try:
            if self.llm_lock is not None:
                with self.llm_lock:
                    result = self.llm_client.chat(
                        messages,
                        max_tokens=self.llm_gate_max_tokens,
                        temperature=0.0,
                        top_p=0.95,
                    )
            else:
                result = self.llm_client.chat(
                    messages,
                    max_tokens=self.llm_gate_max_tokens,
                    temperature=0.0,
                    top_p=0.95,
                )
        except Exception as exc:  # noqa: BLE001
            return GateDecision(
                accepted=True, text=text,
                reason=f"llm_error:{type(exc).__name__}",
            )
        raw = (getattr(result, "text", "") or "").strip()
        should_speak, _ = parse_gate(raw)
        if should_speak:
            return GateDecision(
                accepted=True, text=text, reason="llm_reply",
            )
        return GateDecision(
            accepted=False, text=text, reason="llm_ignore",
        )

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
    from jaeger_os.plugins.whisper_stt._base import DEFAULT_WAKE_PHRASES

    return DEFAULT_WAKE_PHRASES
