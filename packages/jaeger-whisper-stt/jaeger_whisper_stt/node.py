"""Audio session node.

Owns the realtime voice-input session and publishes semantic bus events:
finalized transcripts on ``/sense/stt/transcript``, low-latency speech
start on ``/sense/stt/speech_start``, and deterministic filter decisions on
``/sys/gate/decision``.

The node deliberately keeps mic frames, AEC, VAD, and STT buffering
inside one in-process realtime subsystem.

AEC decoupling (0.9): this module has no dependency on any TTS engine,
at construction time or otherwise — ``AudioSession`` (owned by
``jaeger_os.core.audio``) optionally carries a
``jaeger_os.core.audio.FarEndReference`` (an opaque "pop the currently-
playing audio frames" provider) that ``jaeger_os/nodes/runtime.py``
resolves, discovery-driven, from whatever TTS-slot module happens to be
installed — or leaves ``None`` if none is. This node/session never
imports or names a TTS package; it just uses the provider if one was
handed in. Multiprocess mode should move the far-end reference to a
dedicated binary topic when it needs to cross process boundaries.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.transport import topics
from jaeger_os.core.audio import AudioSession, STTAdapter
from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus


class AudioSessionNode(Node):
    """Poll an :class:`AudioSession` for committed phrases.

    ``AudioSession`` owns mic/AEC/VAD/STT control.  This node owns the
    bus contract around that session.
    """

    def __init__(
        self,
        *,
        bus: Bus,
        session: AudioSession | None = None,
        adapter: STTAdapter | None = None,
        name: str = "audio_session",
        poll_timeout_s: float = 0.5,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        if session is None:
            if adapter is None:
                raise TypeError("AudioSessionNode requires session or adapter")
            session = AudioSession(adapter=adapter)
        self.session = session
        self._poll_timeout_s = poll_timeout_s
        self._final_transcripts = 0
        self._partial_transcripts = 0
        self._speech_starts = 0
        self._gate_decisions = 0

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        """Open the mic + start the STT background loop."""
        self.session.set_on_speech_detected(self._publish_user_speech_start)
        # Wire the gate-decision callback so the node logs gate
        # decisions as bus events the TUI / interfaces render in
        # their voice-activity stream (🤫 ignored / 🎙 accepted).
        try:
            self.session.set_on_gate_decision(self._publish_gate_decision)
        except AttributeError:
            # Older AudioSession (test fixture / pre-refactor build)
            # without the gate-decision API — skip silently.
            pass
        self._wire_partials()
        self._wire_wake_miss()
        self.session.start()
        self._log(
            "audio session started; will publish "
            f"{topics.SENSE_STT_TRANSCRIPT} + {topics.SENSE_STT_SPEECH_START} "
            f"+ {topics.SYS_GATE_DECISION}"
        )

    def tick(self) -> None:
        """Pull one committed phrase per tick and publish it as a
        :class:`Transcript`.

        ``session.next_phrase()`` runs the full input pipeline —
        non-speech filter + self-speech filter + LLM <ignore>/<reply>
        gate — and only returns CONFIRMED phrases.  Anything that
        fails the gate is dropped here and a GateDecision event was
        already emitted to the bus via the callback wired in
        setup().  The brain therefore never sees ambient noise or
        TV / movie audio."""
        phrase = self.session.next_phrase(timeout=self._poll_timeout_s)
        if not phrase:
            return
        # Speech-side timing rides the transcript so the voice loop
        # can report honest user-stops-talking → robot-starts-talking
        # latency (VoiceLLM metrics port). Same-process perf_counter
        # values; 0.0 when the engine doesn't report.
        timing = getattr(self.session, "last_phrase_timing", {}) or {}
        self.publish(topics.Transcript(
            text=phrase,
            is_final=True,
            language=str(getattr(
                getattr(self.session, "adapter", self.session),
                "language", "en",
            )),
            node_id=self.name,
            speech_end_pc=float(timing.get("speech_end", 0.0) or 0.0),
            stt_done_pc=float(timing.get("stt_done", 0.0) or 0.0),
        ))
        self._final_transcripts += 1

    def teardown(self) -> None:
        """Close the mic + stop STT.  Idempotent."""
        try:
            self.session.set_on_speech_detected(None)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.session.set_on_gate_decision(None)
        except Exception:  # noqa: BLE001
            pass
        for target in (self.session, getattr(self.session, "adapter", None)):
            setter = getattr(target, "set_on_partial", None)
            if setter is not None:
                try:
                    setter(None)
                except Exception:  # noqa: BLE001
                    pass
                break
        try:
            self.session.stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"audio session stop error: {type(exc).__name__}: {exc}")

    def _wire_partials(self) -> None:
        """Subscribe to the engine's live text, if it has any.

        Only the streaming methods (``phrase_word``, ``window``,
        ``local_agreement``) expose ``set_on_partial``; the
        phrase-final ones don't have the method at all.  So the absence
        of it is the answer, not an error — a two_pass session simply
        never publishes ``is_final=False`` and interfaces that render
        captions show nothing.  No config flag needed: the method you
        chose already decided.

        The adapter is what owns the callback, and ``AudioSession`` may
        or may not forward the setter, so try the session first and fall
        back to its adapter."""
        for target in (self.session, getattr(self.session, "adapter", None)):
            setter = getattr(target, "set_on_partial", None)
            if setter is not None:
                setter(self._publish_partial)
                self._log("engine emits live partials; publishing "
                          f"{topics.SENSE_STT_TRANSCRIPT} with is_final=False")
                return

    def _wire_wake_miss(self) -> None:
        """Surface speech that was heard but carried no wake phrase.

        Only meaningful when the engine is wake-gated; the rolling
        methods have no engine-side wake stage and simply never fire it.
        Same session-then-adapter probe as ``_wire_partials``, for the
        same reason: the adapter owns the callback and ``AudioSession``
        may or may not forward the setter."""
        for target in (self.session, getattr(self.session, "adapter", None)):
            setter = getattr(target, "set_on_wake_miss", None)
            if setter is not None:
                setter(self._publish_wake_miss)
                return

    def _publish_wake_miss(self, text: str) -> None:
        """Report a heard-but-unaddressed phrase as a gate decision.

        Without this, "you said nothing" and "you didn't say the wake
        word" are the same event on the bus — namely no event — so an
        app cannot tell a dead microphone from a working one that simply
        wasn't addressed. That is the single most common support
        question a wake-gated assistant generates.

        It rides ``/sys/gate/decision`` rather than a new topic because
        it IS a gate decision: a phrase reached the engine and was
        refused. The reason is distinct (``no_wake``) so an interface
        can render it differently from an LLM refusal — one means "say
        the wake word", the other means "I decided you weren't talking
        to me".

        Runs on the decode thread; must not block."""
        try:
            self.publish(topics.GateDecision(
                accepted=False,
                text=str(text)[:200],
                reason="no_wake",
            ))
        except Exception:  # noqa: BLE001 — telemetry never kills decode
            pass

    def _publish_partial(self, text: str) -> None:
        """Forward live text as a non-final transcript.

        Runs on the engine's decode thread ~1x/second and must not
        block.  An empty ``text`` is meaningful — it is how an engine
        says "the phrase closed, clear the caption line" — so it is
        published rather than filtered."""
        try:
            self.publish(topics.Transcript(
                text=text,
                is_final=False,
                language=str(getattr(
                    getattr(self.session, "adapter", self.session),
                    "language", "en",
                )),
                node_id=self.name,
            ))
            self._partial_transcripts += 1
        except Exception:  # noqa: BLE001
            # A caption is a display convenience. Never let publishing
            # one wedge the decode loop that also produces the finals.
            pass

    def _publish_user_speech_start(self) -> None:
        try:
            self.publish(topics.UserSpeechStart(node_id=self.name))
            self._speech_starts += 1
        except Exception:  # a notification must not kill the VAD worker
            pass

    def _publish_gate_decision(self, decision) -> None:
        """Forward gate decisions to the bus so interfaces can render
        them.  Both accepted (audit trail) and ignored (operator's
        voice-activity log).  Callback runs on the polling thread;
        must not block."""
        try:
            self.publish(topics.GateDecision(
                accepted=bool(decision.accepted),
                text=str(decision.text)[:200],
                reason=str(decision.reason),
                node_id=self.name,
            ))
            self._gate_decisions += 1
        except Exception:  # noqa: BLE001
            # Logging callback must never wedge the audio loop.
            pass

    def _engine_health(self) -> dict[str, Any]:
        """Return adapter telemetry without requiring it from test doubles."""
        adapter = getattr(self.session, "adapter", None)
        getter = getattr(adapter, "health", None)
        if getter is None:
            getter = getattr(self.session, "health", None)
        if getter is None:
            return {}
        try:
            value = getter()
            return dict(value) if isinstance(value, dict) else {}
        except Exception as exc:  # health reporting must itself be safe
            return {"last_error": f"health failed: {type(exc).__name__}: {exc}"}

    def health(self) -> dict[str, Any]:
        """Node, recognition worker, and microphone-ingress health in one view."""
        health = super().health()
        health.update({
            "final_transcripts": self._final_transcripts,
            "partial_transcripts": self._partial_transcripts,
            "speech_starts": self._speech_starts,
            "gate_decisions": self._gate_decisions,
            "engine": self._engine_health(),
        })
        return health

    def health_level(self) -> str:
        """Promote silent worker death or missing mic frames to ERROR."""
        base = super().health_level()
        if base == topics.HEALTH_ERROR:
            return base
        engine = self._engine_health()
        if not engine:
            return base
        if engine.get("started") and not engine.get("running"):
            return topics.HEALTH_ERROR
        mic = engine.get("mic") or {}
        if (mic.get("subscribed") and not mic.get("paused")
                and not mic.get("startup_grace") and not mic.get("receiving")):
            return topics.HEALTH_ERROR
        if (engine.get("decode_failures", 0)
                or engine.get("output_drops", 0)
                or mic.get("frames_dropped", 0)
                or mic.get("rate_mismatches", 0)
                or mic.get("invalid_frames", 0)
                or engine.get("last_error")):
            return topics.HEALTH_WARN
        return base


# Back-compat aliases for one release while downstream imports move.
STTNode = AudioSessionNode

__all__ = ["AudioSessionNode", "STTNode", "STTAdapter"]
