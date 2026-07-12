"""Always-on voice for the TUI.

A Jaeger is embodied — like a person, it always listens. The TUI keeps
the microphone live for the whole session through a :class:`VoiceController`,
so the user can talk or type at any moment. The REPL polls
:meth:`VoiceController.poll` alongside stdin; whichever produces input
first becomes the turn.

The controller owns TUI orchestration. The mic/STT/AEC session lives in
the runtime's AudioSessionNode, and the TUI consumes ``/sense/transcript``
from the bus so there is one mic owner in the process.

Settings (see :class:`jaeger_os.core.instance.schemas.VoiceConfig`):
  • wake_word  — require "hey <name>" before the agent answers
  • follow_up  — open a no-wake-word window after each reply
  • barge_in   — interrupt the agent mid-sentence by speaking (needs the
                 speexdsp echo canceller; degrades to mic-pause without)
"""

from __future__ import annotations

import os
import queue
import re
import time
import uuid
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
    from jaeger_whisper_stt.nodes.whisper_stt.engine._base import DEFAULT_WAKE_PHRASES

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
        pending_turn_max_age_s: float = 3.0,
        on_voice_activity: "Any | None" = None,
    ) -> None:
        self.console = console
        self.wake_word = wake_word
        self.follow_up = follow_up
        self.barge_in = barge_in
        self.follow_up_seconds = follow_up_seconds
        self.wake_name = wake_name
        self.pending_turn_max_age_s = pending_turn_max_age_s
        # Callback the TUI registers so /sense/gate_decision events
        # (deterministic filter decisions from AudioSession — non-speech,
        # self-speech, deterministic_pass) render in the operator's
        # voice activity log.  Signature: ``(message: str, kind: str) ->
        # None``.  When None, gate-decision events are not surfaced.
        self._on_voice_activity = on_voice_activity
        self._on_gate_decision: Any = None

        self._audio_session: Any = None
        self._tts: Any = None  # backend reference for AEC wiring only
        self._bus: Any = None
        self._ref: Any = None
        self._chimes: Any = None
        self._transcripts: "queue.Queue[tuple[str, float]]" = queue.Queue(
            maxsize=8,
        )
        self._on_transcript: Any = None
        self._running = False
        # Timestamp tracking for in_followup_window() — the no-wake-word
        # follow-up window after a reply.
        self._followup_active_until: float = 0.0
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
            from jaeger_os.transport import topics
            from jaeger_os.core.audio import AudioSessionConfig
            from jaeger_os.nodes import runtime

            runtime.ensure_tts_node()
            runtime.ensure_audio_session_node(
                config=AudioSessionConfig(
                    stt_mode="two_pass",
                    require_wake_word=self.wake_word,
                    wake_phrases=_wake_phrases(self.wake_name),
                    followup_window_s=self.follow_up_seconds,
                    barge_in=self.barge_in,
                ),
            )
            self._bus = runtime.get_bus()
            self._tts = runtime.get_synth()
            self._audio_session = runtime.get_audio_session()
            if self._audio_session is None:
                raise RuntimeError("audio session did not initialize")
            self._ref = getattr(self._audio_session, "reference_buffer", None)
            self._barge_in_live = bool(
                getattr(self._audio_session, "barge_in_live", False)
            )
            self._on_transcript = self._make_transcript_handler()
            self._bus.subscribe(topics.SENSE_TRANSCRIPT, self._on_transcript)
            # Subscribe to the audio session's gate-decision events so
            # the operator sees what the deterministic filters
            # (non-speech, self-speech) are rejecting in their
            # voice-activity log.  Only wires when the TUI provided a
            # callback — voice_loop / non-TUI consumers don't need it.
            if self._on_voice_activity is not None:
                self._on_gate_decision = self._make_gate_decision_handler()
                self._bus.subscribe(
                    topics.SENSE_GATE_DECISION,
                    self._on_gate_decision,
                )
        except ImportError as exc:
            self.console.print(
                f"[red]Voice unavailable[/] — speech deps missing ({exc}).\n"
                "[dim]Install them with[/] [bold]pip install -e \".[voice]\"[/]."
            )
            self._audio_session = None
            return False
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[red]Couldn't start the microphone:[/] {exc}\n"
                "[dim]Check microphone permissions for your terminal in "
                "System Settings → Privacy & Security.[/]"
            )
            self._audio_session = None
            return False

        # Wake / follow-up earcons — only meaningful with wake gating.
        try:
            from jaeger_os.core.audio import ChimePlayer
            self._chimes = ChimePlayer(
                enabled=self.wake_word, reference_buffer=self._ref,
            )
        except Exception:  # noqa: BLE001
            self._chimes = None

        try:
            from jaeger_ai.agent.tools.speak import warm_kokoro
            warm_kokoro()  # idempotent — usually already warm from boot
        except Exception:  # noqa: BLE001
            pass

        self._running = True
        return True

    def _make_transcript_handler(self):
        def _on_transcript(msg: Any) -> None:
            text = (getattr(msg, "text", "") or "").strip()
            if not text:
                return
            from jaeger_os.core.voice import is_non_speech_marker
            if is_non_speech_marker(text):
                return
            if self._transcripts.full():
                try:
                    self._transcripts.get_nowait()
                except queue.Empty:
                    pass
            self._transcripts.put_nowait((text, time.time()))

        return _on_transcript

    def _make_gate_decision_handler(self):
        """Build a handler that forwards AudioSession's GateDecision
        events to the TUI's voice-activity log.  Runs on the bus
        delivery thread; must not block."""
        def _on_gate_decision(msg: Any) -> None:
            try:
                accepted = bool(getattr(msg, "accepted", False))
                reason = str(getattr(msg, "reason", "") or "")
                phrase = str(getattr(msg, "text", "") or "")
                # Truncate long phrases so the activity log stays tidy.
                if len(phrase) > 60:
                    phrase = phrase[:57] + "..."
                if accepted:
                    # Deterministic-pass means the phrase reached the
                    # brain and ran as a normal turn.  Don't double-log
                    # accept events at this layer.
                    return
                if reason == "non_speech":
                    line = (f"[dim][skipped — non-speech: "
                            f"{phrase!r}][/]")
                    kind = "skipped"
                elif reason == "self_speech":
                    line = (f"[dim]🤫 self-speech filter dropped: "
                            f"{phrase!r}[/]")
                    kind = "gate_ignore"
                else:
                    line = (f"[dim]🤫 voice gate ({reason}): "
                            f"{phrase!r}[/]")
                    kind = "gate_ignore"
                cb = self._on_voice_activity
                if cb is not None:
                    cb(line, kind=kind)
            except Exception:  # noqa: BLE001
                # Logging must never break the audio loop.
                pass

        return _on_gate_decision

    def stop(self) -> None:
        """Tear the mic down. Idempotent."""
        self._running = False
        if self._bus is not None and self._on_transcript is not None:
            try:
                from jaeger_os.transport import topics
                self._bus.unsubscribe(
                    topics.SENSE_TRANSCRIPT,
                    self._on_transcript,
                )
            except Exception:  # noqa: BLE001
                pass
        if self._bus is not None and self._on_gate_decision is not None:
            try:
                from jaeger_os.transport import topics
                self._bus.unsubscribe(
                    topics.SENSE_GATE_DECISION,
                    self._on_gate_decision,
                )
            except Exception:  # noqa: BLE001
                pass
        if self._bus is not None:
            try:
                from jaeger_os.transport import topics
                self._bus.publish(topics.SpeechStop(
                    reason="voice controller stopped",
                    node_id="tui_voice",
                ))
            except Exception:  # noqa: BLE001
                pass
        try:
            from jaeger_os.nodes import runtime
            runtime.shutdown_audio_session_node()
        except Exception:  # noqa: BLE001
            pass
        self._audio_session = None
        self._bus = None
        self._tts = None
        self._ref = self._chimes = None
        self._on_transcript = None
        self._on_gate_decision = None
        self._barge_in_live = False

    # ── input ────────────────────────────────────────────────────────
    def poll(self, timeout: float = 0.25) -> str | None:
        """Return the next committed spoken phrase, or None within
        ``timeout``. Wake-word gating (when on) is handled inside the STT."""
        if self._audio_session is None:
            return None
        try:
            phrase, queued_at = self._transcripts.get(timeout=timeout)
        except queue.Empty:
            return None
        age_s = time.time() - queued_at
        if age_s > self.pending_turn_max_age_s:
            self.console.print(
                f"[dim]🎙  dropped stale voice input after {age_s:.1f}s.[/]"
            )
            return None
        return (phrase or "").strip() or None

    # ── output ───────────────────────────────────────────────────────
    def speak(self, text: str) -> bool:
        """Voice a reply. With live barge-in the mic stays open and the
        user can cut the agent off mid-sentence; otherwise the mic is
        paused for the duration. Returns True if the user barged in.

        The reply is the agent's normal output — the brain is
        transport-agnostic, so there is no <reply>/<ignore> gate to
        parse.  Non-speech markers are dropped; otherwise the text is
        spoken.
        """
        if not text or self._bus is None or self._audio_session is None:
            return False
        from jaeger_os.core.voice import clean_voice_reply
        text = clean_voice_reply(text)
        if not text:
            return False
        from jaeger_os.core.voice import is_non_speech_marker
        if is_non_speech_marker(text):
            return False

        if self._barge_in_live:
            interrupted = {"flag": False}
            speech_cid = uuid.uuid4().hex

            def _on_speech() -> None:
                if not interrupted["flag"]:
                    interrupted["flag"] = True
                    self._publish_speech_stop(
                        speech_cid, reason="user interrupted",
                    )

            self._audio_session.set_on_speech_detected(_on_speech)
            try:
                ack = self._request_speech(text, speech_cid)
            finally:
                self._audio_session.set_on_speech_detected(None)
            if ack is None or not getattr(ack, "ok", False):
                if ack is None:
                    self.console.print("[dim](TTS node timeout)[/]")
                elif not interrupted["flag"]:
                    reason = getattr(ack, "reason", None) or "unknown"
                    self.console.print(f"[dim](couldn't speak: {reason})[/]")
                return interrupted["flag"]
            # Drop phrases VAD finalized during playback (echo / tail) so
            # a stale utterance doesn't become the next turn.
            try:
                self._audio_session.drain_pending()
            except Exception:  # noqa: BLE001
                pass
            self._audio_session.remember_reply(text)
            return interrupted["flag"]

        # No echo cancellation — pause the mic so it doesn't hear the agent.
        self._audio_session.set_paused(True)
        try:
            ack = self._request_speech(text, uuid.uuid4().hex)
            if ack is None:
                self.console.print("[dim](TTS node timeout)[/]")
            elif not getattr(ack, "ok", False):
                reason = getattr(ack, "reason", None) or "unknown"
                self.console.print(f"[dim](couldn't speak: {reason})[/]")
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[dim](couldn't speak: {exc})[/]")
        finally:
            self._audio_session.set_paused(False)
        self._audio_session.remember_reply(text)
        return False

    def _request_speech(self, text: str, correlation_id: str) -> Any:
        """Publish speech intent and wait for the TTS node ack."""
        from jaeger_os.transport import topics

        return self._bus.request(
            topics.SpeechCommand(
                text=text,
                node_id="tui_voice",
                correlation_id=correlation_id,
            ),
            ack_topic=topics.SENSE_SPOKEN,
            timeout_s=180.0,
        )

    def _publish_speech_stop(
        self,
        correlation_id: str | None = None,
        *,
        reason: str = "interrupted",
    ) -> None:
        """Interrupt speech via the bus instead of calling Kokoro directly."""
        if self._bus is None:
            return
        from jaeger_os.transport import topics

        self._bus.publish(topics.SpeechStop(
            reason=reason,
            node_id="tui_voice",
            correlation_id=correlation_id,
        ))

    def chime(self, kind: str) -> None:
        """Play a wake / follow-up earcon. Pauses the mic around it when
        there is no AEC reference to absorb the tone."""
        if self._chimes is None or self._audio_session is None:
            return
        if not self._chimes.enabled(kind):
            return
        pause = self._ref is None
        if pause:
            self._audio_session.set_paused(True)
        try:
            self._chimes.play(kind)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if pause:
                self._audio_session.set_paused(False)

    def open_followup(self) -> None:
        """Open the no-wake-word follow-up window after a reply. No-op
        unless both wake gating and the follow-up setting are on."""
        if self._audio_session is None or not (self.wake_word and self.follow_up):
            # Record the timestamp for in_followup_window() even when
            # wake gating is off.
            import time
            self._followup_active_until = time.time() + self.follow_up_seconds
            return
        import time
        self._followup_active_until = time.time() + self.follow_up_seconds
        try:
            self._audio_session.open_followup()
        except Exception:  # noqa: BLE001
            pass

    def in_followup_window(self) -> bool:
        """True when we're inside the post-reply follow-up window.

        Tracks elapsed time since the last ``open_followup()`` call
        against ``follow_up_seconds``.
        """
        import time
        until = getattr(self, "_followup_active_until", 0.0)
        return time.time() < until

    # ── turn interruption ────────────────────────────────────────────
    def arm_interrupt(self, cancel_event: Any) -> None:
        """While a turn runs, let sustained user speech set ``cancel_event``
        — so the user can cut in and 'get its attention' mid-thought, not
        just mid-sentence. Pair with :meth:`disarm_interrupt` in a finally."""
        if self._audio_session is not None:
            try:
                self._audio_session.set_on_speech_detected(cancel_event.set)
            except Exception:  # noqa: BLE001
                pass

    def disarm_interrupt(self) -> None:
        """Stop letting speech cancel the turn (back to normal listening)."""
        if self._audio_session is not None:
            try:
                self._audio_session.set_on_speech_detected(None)
            except Exception:  # noqa: BLE001
                pass
