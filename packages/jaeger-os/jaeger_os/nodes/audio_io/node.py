"""AudioIONode — the one owner of the microphone and the speaker.

    /act/speaker/pcm ─▶  AudioIONode  ─▶ /sense/mic/pcm

Before this existed, ``whisper_stt`` opened the mic inside its own
engine and ``kokoro_tts`` opened the speaker inside its own player.
Both are ``kind: engine``, and the taxonomy's driver rule says only a
driver-kind module may open a device. Three things that cost:

* **Nothing else could have the mic.** One module held the input
  stream. A wake-word detector, a level meter, a recorder — each would
  have had to fight it for the device.
* **It could not be distributed.** Mic on a Pi, STT on a Mac was
  impossible, because the audio never became a message: it went
  device → library → engine inside one process.
* **The manifests lied by omission.** ``whisper_stt`` declared
  ``consumes: []`` while consuming audio constantly, because the audio
  never crossed a topic the manifest could name.

**Why one node owns BOTH directions.** Echo cancellation needs the mic
frame (near) and what is currently playing (far) together, per frame.
Split mic and speaker into two drivers and that reference has to cross
a boundary 100 times a second. Here both signals are native: playback
passes through :class:`ReferenceBuffer` on its way to the speaker, and
the mic callback pops from the same buffer. The AEC seam that
``nodes/runtime.py`` used to wire between two separate modules is now
internal.

**The audio callback publishes directly.** That is deliberate and it
is safe: the in-process bus hands the message to per-subscriber queues
with ``put_nowait`` and never blocks the caller. What must never
appear in this file is a callback that waits on anything — a blocked
audio thread is a glitch you can hear.

**Pausing is gone, and that is the point.** ``whisper_stt`` used to
pause the mic during playback so the AI would not hear itself. A
shared device cannot honour that: one consumer's pause would starve
every other. With AEC running the pause was never needed, and without
it a consumer drops frames locally — same effect, no device-wide
side effect.
"""

from __future__ import annotations

import sys
import time
import threading
from typing import Any

import numpy as np

from jaeger_os.core.audio.reference_buffer import ReferenceBuffer
from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus, topics

#: 16 kHz mono is what Whisper wants and what the AEC is tuned for.
DEFAULT_SAMPLE_RATE = 16000

#: 10 ms at 16 kHz. speexdsp requires near and far frames of equal,
#: fixed length, so this is the AEC's frame size as much as the mic's.
DEFAULT_FRAME_SAMPLES = 160

#: Playback runs at 24 kHz because that is what its producers generate:
#: Kokoro synthesises at 24 kHz and the chimes are built at 24 kHz.
#: Capture and playback are separate streams and there is no reason
#: they should share a rate — forcing one would mean resampling
#: everything the speaker plays, to no benefit.
DEFAULT_PLAYBACK_RATE = 24000

#: How long a capturing driver may hear nothing before its link is
#: called down. Generous: a frame is due every 10 ms, so 2 s is 200
#: missed frames — long past a hiccup, short enough that an operator
#: is not staring at a green light while the robot is deaf.
LINK_SILENCE_S = 2.0

#: How long to wait before re-opening a mic that failed to open at all.
#: Longer than LINK_SILENCE_S because this is a device that said no —
#: usually a permission not yet granted — and hammering it neither
#: changes the answer nor produces a readable log.
INPUT_RETRY_S = 15.0

#: Playback block size. No echo-cancellation alignment constraint here,
#: and smaller blocks buy underruns.
DEFAULT_PLAYBACK_BLOCK = 480

# Demand-open mode is available for battery-sensitive deployments. Production
# robot speech defaults to a persistent stream because repeatedly negotiating
# CoreAudio/PortAudio hardware adds latency and is a common source of pops.
OUTPUT_IDLE_CLOSE_S = 0.25

# A playing stream should call back every 20 ms. Two seconds allows Bluetooth
# and device-switch hiccups while still recovering from a genuinely wedged
# backend long before a caller's TTS drain timeout.
PLAYBACK_STALL_S = 2.0


class AudioIONode(Node):
    """Owns the audio devices; everything else subscribes."""

    def __init__(
        self,
        *,
        bus: Bus,
        name: str = "audio_io",
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        frame_samples: int = DEFAULT_FRAME_SAMPLES,
        playback_rate: int = DEFAULT_PLAYBACK_RATE,
        playback_block: int = DEFAULT_PLAYBACK_BLOCK,
        audio_backend: str = "avaudio",
        input_device: Any = None,
        aec: Any = None,
        voice_processing: bool | None = None,
        capture: bool = True,
        playback: bool = True,
        keep_output_open: bool = True,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(bus=bus, name=name,
                         install_signal_handlers=install_signal_handlers)
        self._sample_rate = int(sample_rate)
        self._frame_samples = int(frame_samples)
        self._playback_rate = int(playback_rate)
        self._playback_block = int(playback_block)
        self._audio_backend = audio_backend
        self._input_device = input_device
        self._capture = capture
        self._playback = playback
        self._keep_output_open = bool(keep_output_open)

        # The AEC seam. `reference` carries what is being played out;
        # the mic callback subtracts it from what it hears. One buffer,
        # both directions, no cross-module wiring.
        self.reference = ReferenceBuffer(sample_rate=self._sample_rate)
        self._aec = aec
        self._voice_processing = voice_processing

        self._in_stream: Any = None
        self._out_stream: Any = None
        self._out_lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._out_pending: list[np.ndarray] = []
        self._output_idle_at = 0.0

        self._frames_captured = 0
        self._frames_at_open = 0
        self._last_frame_at = 0.0
        self._opened_at = 0.0
        self._input_restarts = 0
        self._last_input_error: str | None = None
        self._input_recovery_thread: threading.Thread | None = None
        #: Monotonic deadline for retrying a mic that never opened. 0.0
        #: means "nothing to retry" — the normal case.
        self._input_retry_at = 0.0
        self._force_portaudio_input = False
        self._input_backend_active: str | None = None
        self._frames_played = 0
        self._underruns = 0
        self._last_playback_callback_at = 0.0
        self._playback_started_at = 0.0
        self._output_restarts = 0
        self._output_flushes = 0
        self._last_output_error: str | None = None
        self._output_flush_requested = False
        # Playback state, reported on ACT_SPEAKER_STATE. A publisher
        # cannot otherwise tell "my audio finished being SENT" from
        # "my audio finished PLAYING" — the second is the one that
        # matters for a done-ack.
        self._playing = False
        self._last_correlation: str | None = None
        self._playback_correlations: list[str | None] = []

    # ── lifecycle ────────────────────────────────────────────────

    def enable_capture(self) -> None:
        """Upgrade a playback-only driver after an explicit listening request.

        The recovery worker opens the mic off the caller thread; existing
        speaker subscriptions and utterances remain uninterrupted.
        """
        if not self._capture:
            self._input_retry_at = time.monotonic()
            self._capture = True

    def setup(self) -> None:
        if self._playback:
            self.subscribe(topics.ACT_SPEAKER_PCM, self._on_speaker_frame)
            self.subscribe(topics.ACT_SPEAKER_STOP, self._on_speaker_stop)
        # SPEAKER FIRST, and the order is load-bearing. Since kokoro-tts
        # 0.10 moved playback onto /act/speaker/pcm, this driver is the
        # only thing in the system that can make a sound — so a
        # microphone that is denied, absent, or parked on a macOS
        # permission prompt must not be able to take the speaker with
        # it. Opened in the other order, one missing input permission
        # silences an entire application, and the only symptom is
        # kokoro's "no drain signal" warning.
        #
        # Same principle as the AEC note above: a missing part costs you
        # that part, never a different one.
        if self._playback and self._keep_output_open:
            self._open_output()
        if self._capture:
            try:
                self._open_input()
            except Exception as exc:  # noqa: BLE001
                # Coming up deaf beats not coming up. `tick()` retries —
                # see _recover_input_if_stalled's never-opened branch.
                #
                # CEILING: this catches a mic that RAISES. One that HANGS
                # inside CoreAudio still parks setup(), so tick() never
                # runs and nothing retries. Playback is unaffected either
                # way, which is what this ordering buys.
                self._last_input_error = f"{type(exc).__name__}: {exc}"
                self._input_retry_at = time.monotonic() + INPUT_RETRY_S
                self._log(f"mic unavailable ({self._last_input_error}); "
                          f"continuing without capture", level="warn")
        self._log(
            f"audio_io: capture={self._capture} "
            f"@ {self._sample_rate}Hz/{self._frame_samples} "
            f"playback={self._playback} @ {self._playback_rate}Hz "
            f"aec={'on' if self._aec is not None else 'off'}"
        )

    def tick(self) -> None:
        # Audio movement is callback-driven. The node thread handles only
        # policy (optional idle close) and recovery; neither belongs in the
        # real-time callback.
        self._service_output_flush()
        self._recover_input_if_stalled()
        self._recover_output_if_stalled()
        self._close_output_if_idle()
        self._sleep_or_stop(0.05)

    def teardown(self) -> None:
        stream, self._in_stream = self._in_stream, None
        self._close_input_bounded(stream)
        self._in_stream = None
        self._close_output()

    def link_ok(self) -> bool:
        """Is the audio hardware actually there?

        A stream object that exists is not enough — what matters is
        that FRAMES ARE MOVING. An input stream can be open and silent
        after the device is unplugged or CoreAudio wedges, and the node
        goes on ticking, reporting RUNNING, hearing nothing.

        Capture is the honest test because it is continuous: if this
        node is capturing and no frame has arrived in
        LINK_SILENCE_S, the link is down whatever the stream object
        says. Playback has no equivalent — silence is a legitimate
        state for a speaker — so an output-only node reports on the
        stream's existence alone.
        """
        if self._capture:
            if self._in_stream is None:
                return False
            if self._frames_captured == self._frames_at_open:
                # Still opening. Not a failure yet — opening the device
                # measures ~3.6s on macOS.
                return self._opened_at == 0.0 or (
                    time.monotonic() - self._opened_at) < LINK_SILENCE_S
            return (time.monotonic() - self._last_frame_at) < LINK_SILENCE_S
        if self._playback:
            if self._playing:
                return (
                    self._out_stream is not None
                    and self._last_playback_callback_at > 0.0
                    and time.monotonic() - self._last_playback_callback_at
                    < PLAYBACK_STALL_S
                )
            return self._out_stream is not None if self._keep_output_open else True
        return None          # neither direction: nothing to be down

    def health(self) -> dict[str, Any]:
        with self._out_lock:
            queued = sum(int(c.size) for c in self._out_pending)
        callback_age = None
        if self._last_playback_callback_at > 0.0:
            callback_age = time.monotonic() - self._last_playback_callback_at
        health = super().health()
        health.update({
            "capture_rate": self._sample_rate,
            "playback_rate": self._playback_rate,
            "capture": self._capture,
            "playback": self._playback,
            "aec": self._aec is not None,
            "link_ok": self.link_ok(),
            "frames_captured": self._frames_captured,
            "input_backend": self._input_backend_active,
            "input_restarts": self._input_restarts,
            "input_recovery_active": bool(
                self._input_recovery_thread
                and self._input_recovery_thread.is_alive()
            ),
            "last_input_error": self._last_input_error,
            "frames_played": self._frames_played,
            "playing": self._playing,
            "underruns": self._underruns,
            "queued_ms": int(queued * 1000 / self._playback_rate),
            "output_open": self._out_stream is not None,
            "keep_output_open": self._keep_output_open,
            "audio_backend": self._audio_backend,
            "playback_callback_age_s": callback_age,
            "output_restarts": self._output_restarts,
            "output_flushes": self._output_flushes,
            "last_output_error": self._last_output_error,
        })
        return health

    def _sleep_or_stop(self, seconds: float) -> None:
        self._stop_event.wait(timeout=seconds)

    # ── capture ──────────────────────────────────────────────────

    def _open_input(self) -> None:
        """Open the mic, preferring AVAudioEngine on macOS.

        Lifted from whisper_stt's ``_MicStream`` — including the
        voice_processing resolution below, which is not obvious and was
        expensive to get right.
        """
        vp = self._voice_processing
        if vp is None:
            # Apple's pipeline (AEC + NS + AGC) is what FaceTime uses
            # and is free on macOS. Turn it OFF when speexdsp AEC is
            # wired: stacking two cancellers double-cancels and adds
            # latency, and the operator's pipeline wants raw samples.
            vp = self._aec is None

        # AVAudioEngine is system-default-only. An explicit device selection
        # must use PortAudio; silently ignoring the operator's device is worse
        # than choosing a different backend to honor it.
        use_avaudio = (
            self._audio_backend == "avaudio"
            and self._input_device is None
            and not self._force_portaudio_input
        )
        if use_avaudio:
            try:
                from jaeger_os.core.audio.avaudio_io import InputStream
                self._in_stream = InputStream(
                    samplerate=self._sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=self._frame_samples,
                    callback=self._on_captured,
                    voice_processing=vp,
                )
                self._in_stream.start()
                self._opened_at = time.monotonic()
                self._frames_at_open = self._frames_captured
                self._input_backend_active = "avaudio"
                if vp:
                    self._log("mic: avaudio voice_processing=on "
                              "(Apple-native AEC + NS + AGC)")
                return
            except Exception as exc:  # noqa: BLE001
                print(f"[{self.name}] avaudio input unavailable ({exc}); "
                      f"falling back to sounddevice",
                      file=sys.stderr, flush=True)

        import sounddevice as sd
        self._in_stream = sd.InputStream(
            device=self._input_device,
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._frame_samples,
            callback=self._on_captured,
        )
        self._in_stream.start()
        self._opened_at = time.monotonic()
        self._frames_at_open = self._frames_captured
        self._input_backend_active = "portaudio"

    def _recover_input_if_stalled(self) -> None:
        """Restart capture off-thread when frames stop moving.

        Native audio teardown/open calls can wedge inside CoreAudio. Keeping
        them off the node tick preserves health heartbeats and makes shutdown
        observable even when the OS audio service is unhealthy.
        """
        if not self._capture or self._stop_event.is_set():
            return
        recovery = self._input_recovery_thread
        if recovery is not None and recovery.is_alive():
            return
        now = time.monotonic()
        if self._in_stream is None:
            # Never opened. setup() no longer lets a failing mic block
            # the speaker, which means this is now the ONLY thing that
            # will ever try again — without this branch, a mic that was
            # denied once stays dead for the life of the process, and
            # granting the permission afterwards changes nothing.
            if self._input_retry_at == 0.0 or now < self._input_retry_at:
                return
            reason = f"mic never opened ({self._last_input_error})"
        else:
            if self._opened_at == 0.0:
                return
            reference = (
                self._last_frame_at
                if self._last_frame_at >= self._opened_at
                else self._opened_at
            )
            if now - reference < LINK_SILENCE_S:
                return
            reason = (
                "no capture frames after open"
                if self._frames_captured == self._frames_at_open
                else f"capture callback stalled for "
                     f"{now - self._last_frame_at:.1f}s"
            )
        self._input_retry_at = now + INPUT_RETRY_S
        self._last_input_error = reason
        self._log(f"mic: {reason}; scheduling recovery", level="warn")
        self._input_recovery_thread = threading.Thread(
            target=self._restart_input,
            name=f"{self.name}-input-recovery",
            daemon=True,
        )
        self._input_recovery_thread.start()

    def _restart_input(self) -> None:
        old, self._in_stream = self._in_stream, None
        self._close_input_bounded(old)
        if self._stop_event.is_set():
            return
        # A stream that opened successfully but never delivered is exactly the
        # AVAudio failure where retrying the same bridge adds little evidence.
        # Fall back to PortAudio on recovery; health reports the active backend.
        if self._input_backend_active == "avaudio":
            self._force_portaudio_input = True
        try:
            self._open_input()
            self._input_restarts += 1
            self._last_input_error = None
            self._input_retry_at = 0.0
            self._log(
                f"mic: recovered on {self._input_backend_active} "
                f"(restart {self._input_restarts})",
                level="ok",
            )
        except Exception as exc:  # noqa: BLE001
            self._last_input_error = f"{type(exc).__name__}: {exc}"
            self._log(f"mic recovery failed: {self._last_input_error}",
                      level="error")

    def _close_input_bounded(self, stream: Any, timeout_s: float = 2.0) -> None:
        """Best-effort native stream close without wedging the node thread."""
        if stream is None:
            return

        def close() -> None:
            for method in ("stop", "close"):
                try:
                    getattr(stream, method)()
                except Exception:  # noqa: BLE001
                    pass

        closer = threading.Thread(
            target=close, name=f"{self.name}-input-close", daemon=True,
        )
        closer.start()
        closer.join(timeout=timeout_s)
        if closer.is_alive():
            self._last_input_error = (
                f"input close exceeded {timeout_s:.1f}s; native audio call wedged"
            )
            self._log(self._last_input_error, level="warn")

    def _on_captured(self, indata, frames, time_info, status) -> None:
        """Audio-thread callback. Must not block, ever."""
        if status:
            print(f"[{self.name}] mic {status}", file=sys.stderr)
        if frames != self._frame_samples:
            return
        mono = np.asarray(indata, dtype=np.float32)[:, 0]
        if self._aec is not None:
            mono = self._cancel_echo(mono)
        self._frames_captured += 1
        self._last_frame_at = time.monotonic()
        try:
            self.publish(topics.AudioInFrame(
                samples=mono.tobytes(),
                sample_rate=self._sample_rate,
                channels=1,
                seq=self._frames_captured,
                node_id=self.name,
            ))
        except Exception as exc:  # noqa: BLE001
            # A publish hiccup must never propagate into the audio
            # thread — it would surface as a dropout, not an error.
            print(f"[{self.name}] mic publish failed: {exc}",
                  file=sys.stderr)

    def _cancel_echo(self, near: np.ndarray) -> np.ndarray:
        far = self.reference.pop_frame(len(near))
        try:
            return self._aec.process(near, far)
        except Exception as exc:  # noqa: BLE001
            print(f"[{self.name}] AEC passthrough on error: {exc}",
                  file=sys.stderr)
            return near

    # ── playback ─────────────────────────────────────────────────

    def _open_output(self) -> None:
        with self._stream_lock:
            if self._out_stream is not None:
                # Tests and alternative drivers may inject an unopened stream.
                # Do not ask the backend to restart on every PCM chunk.
                active = getattr(
                    self._out_stream, "active",
                    getattr(self._out_stream, "started", True),
                )
                if not active:
                    self._out_stream.start()
                self._last_playback_callback_at = time.monotonic()
                return
            if self._audio_backend == "avaudio":
                try:
                    from jaeger_os.core.audio.avaudio_io import OutputStream
                    stream = OutputStream(
                        samplerate=self._playback_rate,
                        channels=1,
                        dtype="float32",
                        blocksize=self._playback_block,
                        callback=self._fill_playback,
                    )
                    self._out_stream = stream
                    stream.start()
                    self._last_playback_callback_at = time.monotonic()
                    self._last_output_error = None
                    return
                except Exception as exc:  # noqa: BLE001
                    self._out_stream = None
                    print(f"[{self.name}] avaudio output unavailable ({exc}); "
                          f"falling back to sounddevice",
                          file=sys.stderr, flush=True)

            import sounddevice as sd
            stream = sd.OutputStream(
                samplerate=self._playback_rate,
                channels=1,
                dtype="float32",
                blocksize=self._playback_block,
                callback=self._fill_playback_sd,
            )
            self._out_stream = stream
            stream.start()
            self._last_playback_callback_at = time.monotonic()
            self._last_output_error = None

    def _close_output(self) -> None:
        with self._stream_lock:
            stream, self._out_stream = self._out_stream, None
        if stream is None:
            return
        for method in ("stop", "close"):
            try:
                getattr(stream, method)()
            except Exception:  # noqa: BLE001
                pass

    def _close_output_if_idle(self) -> None:
        if (self._keep_output_open or self._out_stream is None or self._playing
                or self._output_idle_at <= 0.0):
            return
        if time.monotonic() - self._output_idle_at >= OUTPUT_IDLE_CLOSE_S:
            self._close_output()
            self._output_idle_at = 0.0

    def _recover_output_if_stalled(self) -> None:
        """Restart a playback backend whose callbacks stopped moving.

        The source queue is owned by this node, not the stream, so closing
        and reopening the backend preserves audio that has not yet been
        consumed. Recovery stays off the audio callback to avoid deadlocks.
        """
        if not self._playing or self._out_stream is None:
            return
        last = self._last_playback_callback_at or self._playback_started_at
        if last <= 0.0 or time.monotonic() - last < PLAYBACK_STALL_S:
            return
        self._output_restarts += 1
        self._last_output_error = (
            f"playback callback stalled for {time.monotonic() - last:.2f}s"
        )
        print(
            f"[{self.name}] {self._last_output_error}; restarting output",
            file=sys.stderr,
            flush=True,
        )
        self._close_output()
        try:
            self._open_output()
        except Exception as exc:  # noqa: BLE001
            self._fail_playback(
                f"restart failed: {type(exc).__name__}: {exc}"
            )

    def _service_output_flush(self) -> None:
        """Flush backend-prefetched audio after a barge-in request.

        Clearing ``_out_pending`` stops future callback reads, but AVAudio
        keeps several already-scheduled blocks for glitch-free playback.
        Cycling the stream drops those blocks. This runs on the node thread,
        never the bus callback, because opening hardware may be slow.
        """
        if not self._output_flush_requested:
            return
        self._output_flush_requested = False
        self._output_flushes += 1
        self._close_output()
        if self._keep_output_open and self._playback:
            try:
                self._open_output()
            except Exception as exc:  # noqa: BLE001
                self._last_output_error = (
                    f"flush reopen failed: {type(exc).__name__}: {exc}"
                )
                print(f"[{self.name}] {self._last_output_error}",
                      file=sys.stderr, flush=True)

    def _on_speaker_frame(self, msg: Any) -> None:
        """Anything that wants audio played — TTS, a wake chime, a
        notification — lands here. Three producers share this device
        today; before the driver existed they each opened it.

        The samples go into the AEC reference on the way IN, not on the
        way out of the speaker: the reference must describe what the
        mic is about to hear, and writing it here keeps the canceller
        ahead of the room.
        """
        samples = np.frombuffer(msg.samples, dtype=np.float32)
        if samples.size == 0:
            return

        # Producers declare their own rate. Kokoro synthesises at
        # 24 kHz, chimes are built at 24 kHz, and a caller may hand us
        # something else entirely — resample rather than play it at the
        # wrong pitch.
        rate = int(getattr(msg, "sample_rate", 0)) or self._playback_rate
        playable = self._resample(samples, rate, self._playback_rate)

        # The AEC reference lives at the CAPTURE rate, not the playback
        # rate: it is subtracted from mic frames, so it has to be in the
        # mic's time base. Getting this wrong does not error — it just
        # cancels nothing, which is the kind of bug you chase with your
        # ears.
        # Keep the common 24k -> 16k reference conversion cheap. Importing all
        # of scipy.signal on this bus callback delayed the FIRST audio frame by
        # seconds on a cold process. Linear interpolation is sufficient for an
        # echo reference and has no lazy-import cliff.
        self.reference.write(self._resample_linear(
            samples, rate, self._sample_rate))

        with self._out_lock:
            self._out_pending.append(playable)
            self._last_correlation = msg.correlation_id
            if msg.correlation_id not in self._playback_correlations:
                self._playback_correlations.append(msg.correlation_id)
        self._output_idle_at = 0.0
        if not self._playing:
            self._playback_started_at = time.monotonic()
        self._announce_playback(True)
        try:
            self._open_output()
        except Exception as exc:  # noqa: BLE001
            self._fail_playback(
                f"output open failed: {type(exc).__name__}: {exc}"
            )

    def _on_speaker_stop(self, msg: Any) -> None:
        """Barge-in: drop everything queued, immediately.

        A TTS engine can stop SYNTHESISING on its own, but cannot stop
        the sentence already handed to the device. That half-second is
        what makes an assistant feel deaf when you talk over it.
        """
        with self._out_lock:
            self._out_pending.clear()
        self._output_flush_requested = self._out_stream is not None
        # The echo reference describes audio that will now never be
        # played. Leaving it would have the canceller subtracting a
        # voice the room never heard.
        try:
            self.reference.clear()
        except Exception:  # noqa: BLE001
            pass
        self._output_idle_at = time.monotonic()
        self._announce_playback(False)

    def _announce_playback(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        with self._out_lock:
            queued = sum(int(c.size) for c in self._out_pending)
        # Several producers may queue audio before the device becomes idle.
        # Publish the drain edge for every correlation in that burst so a
        # chime appended after speech cannot strand the speech caller.
        correlations = [self._last_correlation]
        if not playing:
            with self._out_lock:
                correlations = self._playback_correlations or correlations
                self._playback_correlations = []
        for correlation_id in correlations:
            try:
                self.publish(topics.SpeakerState(
                    state="playing" if playing else "idle",
                    queued_ms=int(queued * 1000 / self._playback_rate),
                    underruns=self._underruns,
                    correlation_id=correlation_id,
                    node_id=self.name,
                ))
            except Exception:  # noqa: BLE001
                pass

    def _fail_playback(self, reason: str) -> None:
        """Fail every producer in the current burst immediately."""
        self._last_output_error = reason
        self._playing = False
        self._output_idle_at = time.monotonic()
        with self._out_lock:
            self._out_pending.clear()
            correlations = self._playback_correlations or [
                self._last_correlation
            ]
            self._playback_correlations = []
        print(f"[{self.name}] {reason}", file=sys.stderr, flush=True)
        for correlation_id in correlations:
            try:
                self.publish(topics.SpeakerState(
                    state="error",
                    queued_ms=0,
                    underruns=self._underruns,
                    error=reason,
                    correlation_id=correlation_id,
                    node_id=self.name,
                ))
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _resample(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
        if src == dst or samples.size == 0:
            return samples
        try:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(src, dst)
            return resample_poly(samples, up=dst // g,
                                 down=src // g).astype(np.float32)
        except Exception:  # noqa: BLE001
            # Linear fallback keeps audio at the right PITCH and
            # duration without scipy. Cheaper and rougher; a wrong-pitch
            # voice is far more wrong than a slightly aliased one.
            n = int(round(samples.size * dst / src))
            if n <= 0:
                return np.zeros(0, dtype=np.float32)
            idx = np.linspace(0, samples.size - 1, n, dtype=np.float64)
            return np.interp(idx, np.arange(samples.size),
                             samples).astype(np.float32)

    @staticmethod
    def _resample_linear(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
        if src == dst or samples.size == 0:
            return samples
        n = int(round(samples.size * dst / src))
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        idx = np.linspace(0, samples.size - 1, n, dtype=np.float64)
        return np.interp(idx, np.arange(samples.size),
                         samples).astype(np.float32)

    def _next_playback(self, want: int) -> np.ndarray:
        """Pop exactly ``want`` samples, zero-padded on underrun."""
        out = np.zeros(want, dtype=np.float32)
        filled = 0
        with self._out_lock:
            while filled < want and self._out_pending:
                head = self._out_pending[0]
                take = min(want - filled, head.size)
                out[filled:filled + take] = head[:take]
                filled += take
                if take == head.size:
                    self._out_pending.pop(0)
                else:
                    self._out_pending[0] = head[take:]
        if filled:
            self._frames_played += 1
        return out

    def _fill_playback(self, outdata, frames, time_info, status) -> None:
        self._last_playback_callback_at = time.monotonic()
        outdata[:, 0] = self._next_playback(frames)
        self._maybe_announce_drained()

    def _maybe_announce_drained(self) -> None:
        """Flip to idle the moment the queue empties.

        Published from the audio callback, which is safe for the same
        reason capture is: the bus hands off with put_nowait. It is
        also the only place that knows, since draining is defined by
        the device having consumed everything.
        """
        if not self._playing:
            return
        with self._out_lock:
            empty = not self._out_pending
        if empty:
            self._output_idle_at = time.monotonic()
            self._announce_playback(False)

    def _fill_playback_sd(self, outdata, frames, time_info, status) -> None:
        self._last_playback_callback_at = time.monotonic()
        if status:
            self._underruns += 1
            print(f"[{self.name}] speaker {status}", file=sys.stderr)
        outdata[:, 0] = self._next_playback(frames)
        self._maybe_announce_drained()


__all__ = ["AudioIONode", "DEFAULT_SAMPLE_RATE", "DEFAULT_FRAME_SAMPLES",
           "DEFAULT_PLAYBACK_RATE", "DEFAULT_PLAYBACK_BLOCK",
           "OUTPUT_IDLE_CLOSE_S", "PLAYBACK_STALL_S"]
