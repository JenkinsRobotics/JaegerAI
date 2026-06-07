"""Always-on voice for the TUI.

A Jaeger is embodied — like a person, it always listens. The TUI keeps
the microphone live for the whole session through a :class:`VoiceController`,
so the user can talk or type at any moment. The REPL polls
:meth:`VoiceController.poll` alongside stdin; whichever produces input
first becomes the turn.

The controller owns the STT (VAD-segmented two-pass Whisper), the AEC +
reference buffer that make true barge-in possible, the wake/follow-up
earcons, and the shared Kokoro TTS. It reuses the TUI's already-booted
model — no second model load.

Settings (see :class:`jaeger_os.core.instance.schemas.VoiceConfig`):
  • wake_word  — require "hey <name>" before the agent answers
  • follow_up  — open a no-wake-word window after each reply
  • barge_in   — interrupt the agent mid-sentence by speaking (needs the
                 speexdsp echo canceller; degrades to mic-pause without)
"""

from __future__ import annotations

import os
import re
from typing import Any

from rich.console import Console


# Spoken utterances that turn the mic OFF. Matched only when they are the
# WHOLE phrase, so "should I stop the server" mid-task does not misfire.
_EXIT_PHRASES = (
    "stop", "stop listening", "mic off", "turn off the mic",
    "turn off mic", "turn off the microphone", "go to sleep",
    "stop the mic", "exit voice", "voice off",
)
_EXIT_RE = re.compile(
    r"^\W*(" + "|".join(re.escape(p) for p in _EXIT_PHRASES) + r")\W*$",
    re.IGNORECASE,
)


def is_exit_phrase(text: str) -> bool:
    """True when the user's entire utterance is a mic-off command."""
    return bool(_EXIT_RE.match((text or "").strip()))


def _wake_phrases(name: str | None) -> tuple[str, ...]:
    """Wake phrases for the active instance's name (``hey/ok/okay <name>``).

    "Erin Jaeger" wakes on both ``hey erin`` (the persona) AND ``hey jaeger``
    (the system) — JaegerOS is the platform regardless of the instance's
    persona name, so addressing it by either is natural. The persona phrases
    are listed last so :attr:`wake_word_phrase` shows the persona one in the
    banner. The "jaeger" defaults carry phonetic variants (yeager / yager /
    jager) that Whisper tends to mishear.
    """
    from jaeger_os.plugins.whisper_stt._base import DEFAULT_WAKE_PHRASES

    clean = (name or "").strip().lower()
    if not clean or clean == "jaeger":
        return DEFAULT_WAKE_PHRASES
    first = clean.split()[0]
    persona = tuple(f"{p} {first}" for p in ("ok", "okay", "hey"))
    # System wake first → persona wake last, so wake_word_phrase picks the
    # persona one ("hey erin") for the banner.
    return DEFAULT_WAKE_PHRASES + persona


class VoiceController:
    """Owns the always-on microphone for one TUI session.

    Lifecycle: :meth:`start` builds and starts the mic; :meth:`poll`
    yields spoken phrases; :meth:`speak` voices a reply (barge-in aware);
    :meth:`stop` tears it all down. Build a fresh controller to change
    ``wake_word`` / ``barge_in`` — those are fixed at STT construction.
    """

    def __init__(
        self,
        console: Console,
        *,
        wake_word: bool = False,
        follow_up: bool = True,
        barge_in: bool = False,
        follow_up_seconds: float = 10.0,
        wake_name: str | None = None,
        llm_gate: bool = True,
    ) -> None:
        self.console = console
        self.wake_word = wake_word
        self.follow_up = follow_up
        self.barge_in = barge_in
        self.follow_up_seconds = follow_up_seconds
        self.wake_name = wake_name
        # 0.4.x: when llm_gate is on, the system prompt instructs the
        # agent to begin replies with <ignore>/<reply>; this controller
        # parses the leading tag, suppresses speech on <ignore>, and
        # strips the tag on <reply>.  Matches the VoiceLLM reference's
        # gating strategy that handles 'was that addressed to me?'
        # far more reliably than wake-word transcription matching.
        self.llm_gate = llm_gate
        if llm_gate:
            # Same env var the standalone voice_loop sets — the system
            # prompt's assemble_prompt() conditionally includes the
            # VOICE_LLM_GATE_RULE block when this is "1".
            os.environ["JAEGER_VOICE_GATE"] = "1"

        self._stt: Any = None
        self._tts: Any = None
        self._aec: Any = None
        self._ref: Any = None
        self._chimes: Any = None
        self._running = False
        # True only when barge-in is on AND echo cancellation is live —
        # without AEC an open mic hears the agent, so we fall back to
        # pausing the mic during playback.
        self._barge_in_live = False

    # ── lifecycle ────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._running

    @property
    def wake_word_phrase(self) -> str:
        """The wake phrase to show the user, e.g. 'hey jarvis'."""
        phrases = _wake_phrases(self.wake_name)
        return phrases[-1] if phrases else "hey jaeger"

    @property
    def barge_in_live(self) -> bool:
        """True when barge-in is actually working — barge_in is on AND
        the speexdsp echo canceller loaded. False ⇒ mic-pause fallback."""
        return self._barge_in_live

    def start(self) -> bool:
        """Build + start the mic. Returns True on success, False (with a
        printed reason) if speech deps are missing or the mic won't open."""
        try:
            from jaeger_os.plugins.whisper_stt import WhisperSTTTwoPass
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[red]Voice unavailable[/] — speech deps missing ({exc}).\n"
                "[dim]Install them with[/] [bold]pip install -e \".[voice]\"[/]."
            )
            return False

        from jaeger_os.core.tools.speak import _get_tts
        self._tts = _get_tts()

        # AEC + reference buffer — only when barge-in is wanted AND the
        # speexdsp echo canceller is importable.
        if self.barge_in:
            try:
                from jaeger_os.core.audio import (
                    AECWrapper, ReferenceBuffer, aec_available,
                )
                if aec_available():
                    self._aec = AECWrapper(
                        sample_rate=16000, frame_ms=10, enabled=True,
                    )
                    self._ref = ReferenceBuffer(
                        sample_rate=16000, capacity_seconds=2.0,
                    )
                    self._barge_in_live = True
            except Exception:  # noqa: BLE001
                self._aec = self._ref = None
                self._barge_in_live = False

        try:
            self._stt = WhisperSTTTwoPass(
                require_wake_word=self.wake_word,
                wake_phrases=_wake_phrases(self.wake_name),
                followup_window_s=self.follow_up_seconds,
                aec=self._aec,
                far_end_buffer=self._ref,
            )
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[red]Couldn't start the microphone:[/] {exc}\n"
                "[dim]Check microphone permissions for your terminal in "
                "System Settings → Privacy & Security.[/]"
            )
            self._stt = None
            return False

        # Feed TTS playback into the AEC reference so the open mic can
        # cancel the agent's own voice during barge-in.
        if self._ref is not None:
            self._tts.reference_buffer = self._ref

        # Wake / follow-up earcons — only meaningful with wake gating.
        try:
            from jaeger_os.core.audio import ChimePlayer
            self._chimes = ChimePlayer(
                enabled=self.wake_word, reference_buffer=self._ref,
            )
        except Exception:  # noqa: BLE001
            self._chimes = None

        try:
            self._tts.warm()  # idempotent — usually already warm from boot
        except Exception:  # noqa: BLE001
            pass

        self._stt.start()
        self._running = True
        return True

    def stop(self) -> None:
        """Tear the mic down. Idempotent."""
        self._running = False
        if self._stt is not None:
            try:
                self._stt.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._tts is not None:
            try:
                self._tts.stop()
            except Exception:  # noqa: BLE001
                pass
            if self._ref is not None:
                self._tts.reference_buffer = None
        self._stt = None
        self._aec = self._ref = self._chimes = None
        self._barge_in_live = False

    # ── input ────────────────────────────────────────────────────────
    def poll(self, timeout: float = 0.25) -> str | None:
        """Return the next committed spoken phrase, or None within
        ``timeout``. Wake-word gating (when on) is handled inside the STT."""
        if self._stt is None:
            return None
        try:
            phrase = self._stt.next_phrase(timeout=timeout)
        except Exception:  # noqa: BLE001
            return None
        return (phrase or "").strip() or None

    # ── output ───────────────────────────────────────────────────────
    def speak(self, text: str) -> bool:
        """Voice a reply. With live barge-in the mic stays open and the
        user can cut the agent off mid-sentence; otherwise the mic is
        paused for the duration. Returns True if the user barged in.

        When ``llm_gate`` is on (default), the leading <ignore>/<reply>
        tag the system prompt requires is parsed here.  ``<ignore>``
        suppresses TTS entirely (the operator hears nothing — matches
        VoiceLLM's behaviour for background noise + ambient chatter).
        ``<reply>`` strips the tag and speaks the remainder.
        """
        if not text or self._tts is None or self._stt is None:
            return False

        if self.llm_gate:
            from jaeger_os.core.voice import parse_gate
            should_speak, gated_text = parse_gate(text)
            if not should_speak:
                self.console.print(
                    "[dim]🤫 LLM gate: <ignore> — not addressed to me.[/]"
                )
                return False
            text = gated_text or text

        if self._barge_in_live:
            interrupted = {"flag": False}

            def _on_speech() -> None:
                if not interrupted["flag"]:
                    interrupted["flag"] = True
                    self._tts.stop()

            self._stt.set_on_speech_detected(_on_speech)
            try:
                started = self._tts.play_async(text)
                if not started.get("started"):
                    return False
                self._tts.wait_until_done()
            finally:
                self._stt.set_on_speech_detected(None)
            # Drop phrases VAD finalized during playback (echo / tail) so
            # a stale utterance doesn't become the next turn.
            try:
                self._stt.drain_pending()
            except Exception:  # noqa: BLE001
                pass
            return interrupted["flag"]

        # No echo cancellation — pause the mic so it doesn't hear the agent.
        self._stt.set_paused(True)
        try:
            self._tts.speak(text)
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[dim](couldn't speak: {exc})[/]")
        finally:
            self._stt.set_paused(False)
        return False

    def chime(self, kind: str) -> None:
        """Play a wake / follow-up earcon. Pauses the mic around it when
        there is no AEC reference to absorb the tone."""
        if self._chimes is None or self._stt is None:
            return
        if not self._chimes.enabled(kind):
            return
        pause = self._ref is None
        if pause:
            self._stt.set_paused(True)
        try:
            self._chimes.play(kind)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if pause:
                self._stt.set_paused(False)

    def open_followup(self) -> None:
        """Open the no-wake-word follow-up window after a reply. No-op
        unless both wake gating and the follow-up setting are on."""
        if self._stt is None or not (self.wake_word and self.follow_up):
            return
        try:
            self._stt.open_followup()
        except Exception:  # noqa: BLE001
            pass

    # ── turn interruption ────────────────────────────────────────────
    def arm_interrupt(self, cancel_event: Any) -> None:
        """While a turn runs, let sustained user speech set ``cancel_event``
        — so the user can cut in and 'get its attention' mid-thought, not
        just mid-sentence. Pair with :meth:`disarm_interrupt` in a finally."""
        if self._stt is not None:
            try:
                self._stt.set_on_speech_detected(cancel_event.set)
            except Exception:  # noqa: BLE001
                pass

    def disarm_interrupt(self) -> None:
        """Stop letting speech cancel the turn (back to normal listening)."""
        if self._stt is not None:
            try:
                self._stt.set_on_speech_detected(None)
            except Exception:  # noqa: BLE001
                pass
