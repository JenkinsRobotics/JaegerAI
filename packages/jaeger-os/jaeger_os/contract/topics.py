"""topics.py — single source of truth for JROS node topics.

Lives in ``jaeger_os.contract`` (0.9 contract package): topic names +
msgspec schemas are wire truth, imported by anything that puts a
message on the bus. ``jaeger_os.transport.topics`` re-exports this
module unchanged for the ~60 existing ``from jaeger_os.transport
import topics`` call sites — see that file's docstring.

Pure schemas + constants.  No transport dependency.  Both the
in-process Bus (Track A.2) and the future ZMQ transport (Track A.5)
import from here.

Schemas are :class:`msgspec.Struct`, not Pydantic models — 10×
faster on the transport hot path AND native MessagePack support
for the binary topics (audio frames, vision frames).  Pydantic
stays in JROS for config validation + tool schemas where its
richer ecosystem earns the overhead; transport schemas live where
microseconds matter.  See ``dev/docs/history/ROADMAP_0.4.md`` open question
#2 (resolved): JSON for text topics, MessagePack for binary topics.

Namespace
---------
Paths obey the grammar in :mod:`jaeger_os.contract.paths` —
``/<category>/<class>/<message>``, optionally with an instance id:
``/sense/camera/cam0/image_raw``.  Subscribe to any prefix and the
transport filters for you.

Three categories, split by DIRECTION relative to the brain.  Direction
is the one property of a topic that never becomes debatable — a camera
frame flows in, a pixel buffer flows out, and no argument moves either:

* ``/sense/*`` — input devices: camera, mic, touch, encoders, and
  derived readings (transcript, detections).
* ``/act/*``   — output devices: motor, display, speaker, light, estop.
  A display is an actuator that takes pixels the way a motor is one
  that takes velocity.
* ``/sys/*``   — the framework's own traffic: health, node meta,
  tracing.

The class segment names the DEVICE, and everything about one device
lives under one prefix — its command, its data and its feedback.
Subscribing to ``/act/display/face0/`` shows that device's whole
conversation; splitting feedback into a separate category would
scatter one device across two trees.

Adding a new topic
------------------
1. Add an ``UPPER_SNAKE_CASE`` constant whose value parses under
   :func:`jaeger_os.contract.paths.parse`.
2. Add a :class:`msgspec.Struct` subclass that inherits
   :class:`TopicMessage`, with
   ``topic: str = CONSTANT``.
3. Register it in :data:`TOPIC_TO_CLASS`.
4. Only bump ``topic_v`` (default 1) on breaking payload changes;
   add a migration note in the docstring.

The test suite enforces that every constant in :data:`ALL_TOPICS`
has a registered class, that subclasses pin their constant, and
that ``forbid_unknown_fields=True`` catches typos at decode time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import msgspec


# ── topic name constants ──────────────────────────────────────────
#
# Every constant here is CANONICAL — instance-free.  A system with two
# cameras publishes on /sense/camera/cam0/image_raw and
# /sense/camera/cam1/image_raw; both resolve back to the single
# registration below.  Build a live path with
# :func:`jaeger_os.contract.paths.for_instance`.

# ── /sense/ — input devices ───────────────────────────────────────

SENSE_CAMERA_IMAGE_RAW = "/sense/camera/image_raw"
SENSE_MIC_PCM = "/sense/mic/pcm"
SENSE_TOUCH_EVENT = "/sense/touch/event"
SENSE_PROPRIO_STATE = "/sense/proprio/state"

# Derived readings.  Still inputs: they flow toward the brain, and
# nothing downstream cares whether a reading came off a wire or out of
# a model.
SENSE_STT_TRANSCRIPT = "/sense/stt/transcript"
SENSE_STT_SPEECH_START = "/sense/stt/speech_start"
SENSE_VISION_ANALYSIS = "/sense/vision/analysis"

# ── /act/ — output devices ────────────────────────────────────────

# A display is an actuator that takes pixels the way a motor is one
# that takes velocity.  One prefix carries the whole conversation with
# it: what to play, the pixels, how it is going.
#
# There used to be two of each of these — an "animation" set and a
# "media" set — purely so a renderer could subscribe to the face
# without also receiving arbitrary media playback.  That was a
# workaround for a flat namespace.  The instance segment does that job
# now (/act/display/face0/ vs /act/display/media0/), so one set of
# messages serves both and the adapter field says what is playing.
ACT_DISPLAY_PLAY = "/act/display/play"
ACT_DISPLAY_STOP = "/act/display/stop"
ACT_DISPLAY_FRAME = "/act/display/frame"
ACT_DISPLAY_STATE = "/act/display/state"
# Render telemetry is a SEPARATE topic, not a field on the frame: a
# host asking "is this face keeping up?" must not have to subscribe to
# the pixel stream to find out.  Published on a low fixed cadence.
ACT_DISPLAY_STATS = "/act/display/stats"

ACT_SPEECH_SAY = "/act/speech/say"
ACT_SPEECH_STOP = "/act/speech/stop"
ACT_SPEECH_SPOKEN = "/act/speech/spoken"     # done-ack, back from the device
ACT_SPEECH_CHUNK = "/act/speech/chunk"       # per-chunk AMPLITUDE, for
                                             # lip-sync — not the audio,
                                             # which is ACT_SPEAKER_PCM
# The speaker, shaped like every other output device: what to play,
# how to interrupt it, and how it is going. Same three-part shape as
# /act/display/{play,stop,state} — a driver you cannot tell to stop,
# and cannot ask whether it finished, is not a finished driver.
ACT_SPEAKER_PCM = "/act/speaker/pcm"
ACT_SPEAKER_STOP = "/act/speaker/stop"
ACT_SPEAKER_STATE = "/act/speaker/state"

ACT_MOTOR_COMMAND = "/act/motor/command"
ACT_LIGHT_SET = "/act/light/set"
ACT_ESTOP_TRIGGER = "/act/estop/trigger"

ACT_TIMELINE_RUN = "/act/timeline/run"
ACT_TIMELINE_PROGRESS = "/act/timeline/progress"

# ── /sys/ — the framework's own traffic ───────────────────────────

# Node introspection.  Every node announces what it is and what it
# talks to, so a live system can be asked what is publishing what
# without reading anyone's source.  ROS gets the same answer from
# `ros2 topic info`.
SYS_NODE_HEALTH = "/sys/node/health"
SYS_NODE_META = "/sys/node/meta"
SYS_TRACE_STEP = "/sys/trace/step"
SYS_GATE_DECISION = "/sys/gate/decision"

# Skill-tree events.  These are PRODUCT-tier — they neither sense the
# world nor command it, and they only exist because one consumer
# (JaegerAI) emits them.  Parked under /sys/ because the framework
# contract is where they currently live, not because they belong here.
# Evicting them is safe whenever JaegerAI's pinned jaeger-os is bumped.
SYS_SKILL_XP_AWARDED = "/sys/skill/xp_awarded"
SYS_SKILL_LEVEL_UP = "/sys/skill/level_up"
SYS_SKILL_UNLOCKED = "/sys/skill/unlocked"
SYS_SKILL_MASTERED = "/sys/skill/mastered"


# ── common envelope ────────────────────────────────────────────────

class TopicMessage(
    msgspec.Struct,
    kw_only=True,
    forbid_unknown_fields=True,
):
    """Common envelope every topic payload inherits.

    ``kw_only=True`` lets subclasses freely mix required and default-
    bearing fields without dataclass-style ordering pain.

    ``forbid_unknown_fields=True`` makes msgspec raise on unknown
    keys during decode — analogous to Pydantic's ``extra="forbid"``
    so a typo'd field name on the wire is a hard error, not a
    silent drop.

    Subclasses pin ``topic`` to a Literal whose only value is the
    matching constant.  msgspec validates this at decode time too.
    """
    topic: str
    topic_v: int = 1
    t_emit_ns: int = msgspec.field(default_factory=time.time_ns)
    seq: int = 0
    node_id: str = ""
    correlation_id: str | None = None


# ── /sense/* ───────────────────────────────────────────────────────

class AudioInFrame(TopicMessage):
    """Raw mic samples from an audio_in node.  Binary payload —
    intended for MessagePack on the wire (msgspec encodes ``bytes``
    natively; JSON would need a base64 hop)."""
    topic: str = SENSE_MIC_PCM
    samples: bytes = b""  # float32 little-endian PCM
    sample_rate: int = 16000
    channels: int = 1


class Transcript(TopicMessage):
    """STT output for a finalized utterance."""
    topic: str = SENSE_STT_TRANSCRIPT
    text: str = ""
    confidence: float = 0.0   # 0..1; 0.0 = unknown
    language: str = "en"
    is_final: bool = True
    duration_s: float = 0.0
    # Speech-side timing (VoiceLLM metrics port): ``time.perf_counter()``
    # stamps from the STT engine — when the VAD silence hangover closed
    # the phrase, and when the accurate transcription finished. 0.0 =
    # unknown (engine doesn't report). perf_counter values are only
    # comparable WITHIN one process — fine for the voice loop's
    # speech-end→speak latency, meaningless across machines.
    speech_end_pc: float = 0.0
    stt_done_pc: float = 0.0


class UserSpeechStart(TopicMessage):
    """Low-latency event emitted when the audio session detects
    sustained user speech.

    This is distinct from :class:`Transcript`: speech-start is for
    realtime interruption/barge-in and arrives before Whisper finalizes
    a phrase; transcript is the later semantic user utterance.
    """
    topic: str = SENSE_STT_SPEECH_START


class GateDecision(TopicMessage):
    """Per-phrase decision the audio session's input pipeline made
    about whether to publish a transcript.

    Published by the audio session node for EVERY phrase that passes
    the STT stage — including ignored ones — so interfaces can
    render their voice-activity log (🤫 ignored / 🎙 accepted).
    Only ACCEPTED phrases also become a ``Transcript`` on
    ``/sense/stt/transcript`` and reach the brain.

    Reason values:
      ``no_wake``     — heard, but carried no wake phrase, so the STT
                        engine never forwarded it.  The only reason
                        raised by the STT stage itself rather than the
                        session's filters, and the one that answers the
                        most common question a wake-gated assistant
                        gets: "why didn't it respond?"  Without it,
                        "nothing was said" and "you weren't addressing
                        me" are the same thing on the bus — namely no
                        message at all.
      ``llm_reply``   — LLM gate accepted as addressed to assistant
      ``llm_ignore``  — LLM gate rejected as not addressed
      ``non_speech``  — non-speech marker filter dropped it
      ``self_speech`` — self-speech similarity filter dropped it
      ``no_client``   — gate skipped (no LLM client wired yet)
      ``gate_off``    — operator disabled LLM gate via config
      ``llm_error:<Type>`` — gate call failed; accepted as fallback

    Pattern (operator-locked 2026-06-07): the node owns its full
    input pipeline.  This topic exists so the operator sees what
    the gate decided without the brain having to know voice exists.
    """
    topic: str = SYS_GATE_DECISION
    accepted: bool = False
    text: str = ""
    reason: str = ""


class CameraFrame(TopicMessage):
    """A single camera frame.  Binary payload — rides MessagePack
    on the wire so the encoded image bytes don't pay a base64 hop.

    Schema is intentionally lean: a camera node is a source, not
    an analyser.  No YOLO boxes, no scene descriptions, no
    detection metadata — those belong on a future
    ``/sense/vision/analysis`` topic published by a downstream
    inference node that consumes ``/sense/camera/image_raw``.

    Two source modes supported by the vision node (Track B.5):
        * USB camera (cv2.VideoCapture device index, local Mac)
        * TCP stream (frames pushed by a remote board over an
          Ethernet socket — today: JP01-VCC01 Jetson; tomorrow:
          any IP-streamable source)

    The brain doesn't care which mode produced a frame — same
    topic, same schema; only ``camera_id`` distinguishes sources
    when multiple cameras run at once.
    """
    topic: str = SENSE_CAMERA_IMAGE_RAW
    image_w: int = 0
    image_h: int = 0
    encoding: str = "jpeg"  # "jpeg" | "png" | "raw_bgr8" | "raw_rgb8"
    frame_bytes: bytes = b""
    camera_id: str = "default"
    frame_seq: int = 0  # monotonic counter from the producing camera


class TouchReading(TopicMessage):
    """Contact-sensor reading from skin / bumpers."""
    topic: str = SENSE_TOUCH_EVENT
    sensor_id: str = ""
    in_contact: bool = False
    force_n: float = 0.0


class ProprioReading(TopicMessage):
    """Encoder + IMU state from JP01-MC01 (ESP32 motion controller)."""
    topic: str = SENSE_PROPRIO_STATE
    joints_rad: list[float] = msgspec.field(default_factory=list)
    joints_vel_rps: list[float] = msgspec.field(default_factory=list)
    imu_quat: list[float] = msgspec.field(default_factory=list)
    # imu_quat: [w, x, y, z]
    imu_omega: list[float] = msgspec.field(default_factory=list)
    # imu_omega: [wx, wy, wz]


class SpokenAck(TopicMessage):
    """TTS-done acknowledgement.  Published by the tts node after the
    audio_out node finishes playing the synthesized clip.  The brain's
    text_to_speech tool waits on this (correlation_id-matched) before
    returning to the agent loop."""
    topic: str = ACT_SPEECH_SPOKEN
    ok: bool = False
    #: ELAPSED time to satisfy the request, not the length of the audio.
    #: Includes synthesis, and on a cold engine the model load too — so
    #: a 2 s sentence can legitimately ack 30 s the first time. Say it
    #: here because the name reads like audio duration and a lip-sync
    #: consumer that believed that would be wrong by an order of
    #: magnitude. Per-chunk amplitude on ACT_SPEECH_CHUNK is the signal
    #: for anything that has to move in time with the voice.
    duration_s: float = 0.0
    reason: str | None = None  # populated when ok=False


class TtsChunk(TopicMessage):
    """Per-chunk TTS amplitude event.  Published at ~30 Hz by the TTS
    node during ``synthesizer.speak()``; drives lip-sync on the
    AnimationNode side.

    0.5.0 ships with a sin-wave amplitude proxy — the chunks fire
    at a fixed rate while synthesis is in progress, with amplitude
    oscillating to simulate mouth movement.  0.5.x will replace
    this with real RMS sampling from Kokoro's audio buffer once
    the synthesizer exposes a streaming callback.

    Amplitude is normalised to ``[0.0, 1.0]``.  Subscribers that
    want decibels or raw samples should request a different topic
    (not yet defined).
    """
    topic: str = ACT_SPEECH_CHUNK
    amplitude: float = 0.0          # 0.0..1.0
    is_final: bool = False          # True on the last chunk of an utterance


class TraceStep(TopicMessage):
    """One step in an agent turn's pipeline — emitted live as the turn
    runs so a Studio panel can follow the flow (``input`` -> ``tool``...
    -> ``think`` -> ``answer``), and recorded to ``logs/trace.jsonl`` for
    the historic baseline.  Flow + timings only — no model reasoning text.

    ``dur_s`` is the step's own duration; the terminal ``answer`` step
    carries the whole turn's wall time.  ``detail`` is a short (<=200
    char) input/output preview, never the full payload."""
    topic: str = SYS_TRACE_STEP
    turn_id: int = 0
    step_seq: int = 0
    kind: str = ""        # input | think | tool | answer
    name: str = ""        # tool name (tool steps), else ""
    t_offset_s: float = 0.0
    dur_s: float = 0.0
    ok: bool = True
    detail: str = ""
    session: str = ""


# ── /act/* ─────────────────────────────────────────────────────────

class SpeechCommand(TopicMessage):
    """Brain → tts: speak the given text.  Set ``correlation_id`` to
    match against the :class:`SpokenAck` reply (the tool-RPC pattern).

    An empty ``voice`` uses the module's configured default. ``rate`` is a
    multiplier and production TTS modules should reject unsafe extremes.
    """
    topic: str = ACT_SPEECH_SAY
    text: str = ""
    voice: str = ""
    rate: float = 1.0  # 1.0 = normal speed


class AudioOutFrame(TopicMessage):
    """Audio bound for the speaker.  Binary payload.

    Anything may publish this — a TTS engine, a wake chime, a
    notification sound.  ``sample_rate`` is the PRODUCER's rate, not
    the device's: the driver resamples.  Declaring it wrong does not
    raise, it just plays at the wrong pitch.

    Set ``correlation_id`` to learn when this specific audio finished:
    the driver echoes the last id it consumed on
    :data:`ACT_SPEAKER_STATE`.
    """
    topic: str = ACT_SPEAKER_PCM
    samples: bytes = b""  # float32 little-endian PCM
    sample_rate: int = 24000
    channels: int = 1


class SpeakerStop(TopicMessage):
    """Drop everything queued for the speaker, now.

    This is barge-in: the user started talking over the AI, and the
    audio already handed to the driver has to go. Without it a TTS
    engine can stop SYNTHESISING but cannot stop the sentence already
    in flight, which is the half-second that makes an assistant feel
    deaf.
    """
    topic: str = ACT_SPEAKER_STOP


class SpeakerState(TopicMessage):
    """The speaker reporting on itself.

    ``state`` flips to ``"idle"`` when the queue drains, which is how a
    publisher learns its audio finished PLAYING rather than merely
    finished being sent. ``"error"`` completes the same wait as a failure
    and carries a human-readable reason. A TTS engine that owned its own device could
    just block on drain; one that publishes has to be told.

    ``correlation_id`` (inherited) carries the id of the last frame
    actually consumed, so a publisher can tell its own utterance
    finishing from someone else's.
    """
    topic: str = ACT_SPEAKER_STATE
    state: str = "idle"            # "playing" | "idle" | "error"
    queued_ms: int = 0             # audio still to play
    underruns: int = 0             # cumulative; a rising count is a
                                   # producer that cannot keep up
    error: str | None = None


class EStop(TopicMessage):
    """System e-stop — L2 of the hardware safety contract (see
    dev/docs/hardware/JROS_HARDWARE_FRAMEWORK_PLAN.md §2.8). Publishing with
    ``engaged=True`` LATCHES the stop: every hardware node in the
    package's ``safety.estop_scope`` executes its node-local stop on
    receipt, and motion capabilities refuse while latched. Release
    (``engaged=False``) is an explicit operator action — the framework
    never auto-releases."""
    topic: str = ACT_ESTOP_TRIGGER
    engaged: bool = True
    reason: str = ""
    source: str = ""   # "operator" / "agent" / "button" / "supervisor"


#: Health severity, the ROS ``diagnostic_msgs`` levels.
#:
#: ``STALE`` is deliberately NOT self-reportable: a node that has stopped
#: heartbeating cannot tell you it stopped. Only a consumer watching the
#: clock can decide that — see ``jaeger_os.app.health.HealthCache``.
HEALTH_OK = "OK"
HEALTH_WARN = "WARN"
HEALTH_ERROR = "ERROR"
HEALTH_STALE = "STALE"
HEALTH_LEVELS = (HEALTH_OK, HEALTH_WARN, HEALTH_ERROR, HEALTH_STALE)


class NodeHealth(TopicMessage):
    """Periodic node liveness heartbeat.

    ``state`` mirrors ``jaeger_os.nodes.base.NodeState``;
    ``link_connected`` and ``last_controller_rx_age_s`` describe the
    hardware link when the node owns one (0-default = not applicable).

    ``level`` is severity, separate from ``state``. A node can be
    RUNNING and unwell — dropping 40% of frames, or erroring every other
    tick — and without a level it reports exactly what a healthy one
    does. That is the distinction ROS's diagnostic levels exist for.

    The telemetry fields are measured by the ``Node`` base for EVERY
    node, not hand-built per module. Mochi 3.0 carried ``fps_target`` /
    ``memory_mb`` / ``tx_rate_mbps`` in its node base and that turned
    out to be the right home: any node can be asked whether it is
    keeping up, without each one inventing its own answer.
    """
    topic: str = SYS_NODE_HEALTH
    node: str = ""
    state: str = ""
    level: str = HEALTH_OK
    link_connected: bool = False
    last_controller_rx_age_s: float = 0.0
    detail: str = ""
    # ── measured by the Node base ──
    uptime_s: float = 0.0
    tick_rate_hz: float = 0.0   # measured, vs whatever tick_interval asked for
    tx_rate_hz: float = 0.0     # messages published per second
    msgs_out: int = 0           # cumulative since start
    tick_errors: int = 0        # cumulative; a rising count is the WARN
    memory_mb: float = 0.0      # peak RSS for the process


class NodeMeta(TopicMessage):
    """A node announcing itself: identity, and what it talks to.

    Published once when the node reaches RUNNING, and again on request,
    so anything that attaches later can rebuild the picture. Together
    across all nodes these form the **bus catalog** — the answer to
    "what is running, and what does it publish?" that otherwise requires
    reading source.

    ``subscribes`` is observed, not declared: the base class records
    what the node actually subscribed to. A module's ``module.yaml``
    declares INTENT; this reports REALITY, and the two disagreeing is
    itself worth knowing.

    ``publishes`` is likewise observed — topics seen leaving this node —
    so it fills in as the node runs rather than being complete at
    startup.
    """
    topic: str = SYS_NODE_META
    node: str = ""
    node_class: str = ""       # implementing class, for "which module is this?"
    state: str = ""            # NodeState at announcement time
    subscribes: list[str] = msgspec.field(default_factory=list)
    publishes: list[str] = msgspec.field(default_factory=list)
    pid: int = 0               # which process — the answer for subprocess nodes
    started_at_ns: int = 0


class MotionCommand(TopicMessage):
    """Brain → motor_ctrl (JP01-MC01 ESP32): motion command.

    Two complementary modes:
        * velocity — set ``linear_*``/``angular_z``, held for
          ``duration_s`` seconds.
        * waypoint — set ``use_waypoint=True`` and ``target_xy`` to
          [x, y] in metres (frame TBD by motor_ctrl).
    """
    topic: str = ACT_MOTOR_COMMAND
    linear_x_mps: float = 0.0
    linear_y_mps: float = 0.0
    angular_z_rps: float = 0.0
    duration_s: float = 0.0
    use_waypoint: bool = False
    target_xy: list[float] = msgspec.field(default_factory=list)


class SpeechStop(TopicMessage):
    """Voice loop → TTS node: stop the current speech.  Barge-in
    primitive — when the STT side detects sustained user voice
    during TTS playback, the voice loop publishes this so the TTS
    node interrupts its synthesizer.  The TTS node then publishes
    a SpokenAck with ``ok=False`` / ``reason="interrupted"`` for
    any in-flight bus.request waiting on the matching
    correlation_id.

    Reasonably blast-radius'd: callers don't need to know which
    correlation_id is in flight; the TTS node maintains its own
    state.  Pass ``correlation_id`` if you want the ack to be tied
    back, otherwise the node uses whatever it's currently working
    on."""
    topic: str = ACT_SPEECH_STOP
    reason: str = "interrupted"


class LightCommand(TopicMessage):
    """Brain → led_ctrl (JP01-AVC01 Teensy): RGB LED state.

    ``rgb`` is a list of 3 ints in [0, 255].  ``pattern`` is the
    playback shape; "solid" holds the colour, "pulse"/"rainbow"
    animate, "off" blanks the strip.  ``duration_ms=0`` means hold
    until the next command."""
    topic: str = ACT_LIGHT_SET
    strip_id: str = "default"
    rgb: list[int] = msgspec.field(default_factory=lambda: [0, 0, 0])
    pattern: str = "solid"  # "solid" | "pulse" | "rainbow" | "off"
    duration_ms: int = 0


# ── display / timeline / skill-tree ────────────────────────────────
#
# One set of messages, not two.  Until 0.9 there was an "animation"
# set and a "media" set carrying nearly identical fields, kept apart so
# a renderer could subscribe to the face without also receiving
# arbitrary media playback.  The instance segment does that now —
# /act/display/face0/ and /act/display/media0/ are different prefixes —
# so the duplication bought nothing and cost a second decoder path.

class DisplayCommand(TopicMessage):
    """Brain / Studio → a display: play this asset.

    ``adapter`` names the decoder (image/bitmap/sprite/gif/video/math),
    or ``"auto"`` — the default — to pick it from the file extension.
    Auto is the default because the alternative footgun is silent: name
    a concrete decoder and a ``.gif`` handed to the image adapter shows
    one motionless frame with no error anywhere.

    ``asset_path`` resolves against the active instance's asset
    directory.  ``params`` carries adapter-specific options (fit_mode,
    loop, speed, ...).  ``duration_ms=0`` means play to natural end —
    an image holds, a gif runs one pass, a video plays out.

    A new command preempts whatever is playing.
    """
    topic: str = ACT_DISPLAY_PLAY
    adapter: str = "auto"
    asset_path: str = ""
    duration_ms: int = 0
    params: dict = msgspec.field(default_factory=dict)


class DisplayStop(TopicMessage):
    """Stop what is playing; revert to idle/default."""
    topic: str = ACT_DISPLAY_STOP


@dataclass
class FrameBuffer:
    """One rendered frame, in-process.  ``data`` is raw RGBA8 bytes
    (4 bytes/pixel, row-major): ``width * height * 4 == len(data)``.

    The canonical definition.  Every adapter in every animation module
    produces this shape so the bus and every renderer agree on one
    format.  Before this lived here, each producer defined its own and
    identical decoders were duplicated purely to satisfy a second
    import — the "two copies of one truth" failure CONVENTIONS.md law 1
    warns about.

    Not a :class:`TopicMessage`: this is the buffer an adapter hands the
    node.  :class:`DisplayFrame` is its on-bus form.
    """

    width: int
    height: int
    data: bytes  # RGBA8, w*h*4 bytes
    duration_ms: int = 0  # how long this frame stays visible
    is_final: bool = False  # last frame of a one-shot clip


class DisplayFrame(TopicMessage):
    """A display node → renderers: one RGBA8 frame, ``width*height*4``
    bytes, row-major.  The on-bus form of :class:`FrameBuffer`.

    ``duration_ms`` and ``is_final`` are what make this more than a
    pixel dump.  A decoder genuinely knows both — a GIF's inter-frame
    delays vary within one file — and without them a subscriber has to
    guess a frame rate and infer clip ends from a separate topic with
    no ordering guarantee.  The envelope's inherited ``seq`` lets a
    consumer detect drops.

    SIZE MATTERS HERE.  At 64x64 this is 16 KB and riding the bus is
    free; at 4K it is 33 MB, and 30 fps of that is ~1 GB/s — fine
    in-process (the object is passed by reference, never copied) and
    hopeless over any link.  A display that can render for itself
    should subscribe to :data:`ACT_DISPLAY_PLAY` and never to this
    topic, so the broker never forwards the pixels at all.  Frames on
    the bus are for sinks that CANNOT render: an LED matrix, JP01's
    AVC01.
    """
    topic: str = ACT_DISPLAY_FRAME
    data: bytes = b""
    width: int = 0
    height: int = 0
    duration_ms: int = 0
    is_final: bool = False


class DisplayStats(TopicMessage):
    """animation node → operator surfaces: render telemetry.

    Separate from the frame topic on purpose: a host monitoring a face's
    health (is it keeping up? is it dropping frames?) must not have to
    subscribe to the full pixel stream to find out.  Published on a low
    fixed cadence, not per frame.

    ``fps_actual`` vs ``fps_target`` is the number that matters on
    constrained hardware — an engine can render far faster than a wire
    can carry, and the gap is invisible without this.
    """
    topic: str = ACT_DISPLAY_STATS
    adapter: str = ""          # adapter currently bound ("gif", "math", ...)
    asset_path: str = ""       # what is playing, "" when idle
    width: int = 0
    height: int = 0
    fps_actual: float = 0.0    # measured over the last window
    fps_target: float = 0.0    # what the clip's pacing asks for
    frames_emitted: int = 0    # cumulative since node start
    frames_dropped: int = 0    # commands discarded by a full queue
    decode_ms: float = 0.0     # mean time in the adapter per frame
    queue_depth: int = 0       # pending commands


class TimelineCommand(TopicMessage):
    """Brain → animation_node + tts_node + motor_node: play a
    multi-track timeline (greeting, performance, scripted sequence).

    The timeline body is a JSON-serialised OTIO-shaped dict carried
    inline OR a name resolved against ``<instance>/timelines/*.json``.
    Bus consumers (animation node for animation tracks, tts node for
    speech tracks, etc.) extract their relevant track and schedule
    its events.

    See dev/docs/avatar/0.5.0_timeline_schema.md for the schema."""
    topic: str = ACT_TIMELINE_RUN
    name: str = ""                # named timeline from instance dir; "" → inline
    timeline_json: str = ""       # serialised when inline
    loop: bool = False


class DisplayState(TopicMessage):
    """A display → surfaces: what it is playing and how far in.

    Feedback lives under the same prefix as the command on purpose:
    subscribing to ``/act/display/face0/`` shows that device's whole
    conversation, request and response together.
    """
    topic: str = ACT_DISPLAY_STATE
    adapter: str = ""
    asset_path: str = ""
    state: str = "idle"           # "idle" | "playing" | "stopping"
    progress: float = 0.0         # 0..1 within current asset
    elapsed_ms: int = 0
    reason: str = ""              # why it stopped, when it did


class TimelineProgress(TopicMessage):
    """Animation node / timeline runner → bus: timeline scheduling
    progress.  Lets the brain know when scripted sequences finish."""
    topic: str = ACT_TIMELINE_PROGRESS
    timeline_name: str = ""
    state: str = "running"        # "running" | "complete" | "interrupted"
    elapsed_ms: int = 0
    duration_ms: int = 0


class XpAwarded(TopicMessage):
    """Skill-tree XP grant event.  Emitted by ``xp_emitter`` whenever
    a tool dispatch / bench pass / milestone awards XP to a skill.
    Subscribers: the skill_tree registry (which persists state), and
    eventual visualisation surfaces.

    See dev/docs/skills/SKILL_TREE.md for the XP-progression contract."""
    topic: str = SYS_SKILL_XP_AWARDED
    skill_id: str = ""
    amount: int = 0
    reason: str = ""
    metadata: dict = msgspec.field(default_factory=dict)


class SkillLevelUp(TopicMessage):
    """Skill-tree level-up event.  Fired by the registry when a skill
    crosses its xp_to_next_level threshold."""
    topic: str = SYS_SKILL_LEVEL_UP
    skill_id: str = ""
    new_level: int = 0


class SkillUnlocked(TopicMessage):
    """Skill-tree unlock event.  Fired when a skill's prerequisites
    are all satisfied, transitioning it from ``locked`` →
    ``available``."""
    topic: str = SYS_SKILL_UNLOCKED
    skill_id: str = ""


class SkillMastered(TopicMessage):
    """Skill-tree mastery event.  Fired when XP crosses xp_to_mastery."""
    topic: str = SYS_SKILL_MASTERED
    skill_id: str = ""


# ── registry + lookup ─────────────────────────────────────────────

TOPIC_TO_CLASS: dict[str, type[TopicMessage]] = {
    # /sense/ — input devices
    SENSE_CAMERA_IMAGE_RAW: CameraFrame,
    SENSE_MIC_PCM: AudioInFrame,
    SENSE_TOUCH_EVENT: TouchReading,
    SENSE_PROPRIO_STATE: ProprioReading,
    SENSE_STT_TRANSCRIPT: Transcript,
    SENSE_STT_SPEECH_START: UserSpeechStart,
    # /act/ — output devices
    ACT_DISPLAY_PLAY: DisplayCommand,
    ACT_DISPLAY_STOP: DisplayStop,
    ACT_DISPLAY_FRAME: DisplayFrame,
    ACT_DISPLAY_STATE: DisplayState,
    ACT_DISPLAY_STATS: DisplayStats,
    ACT_SPEECH_SAY: SpeechCommand,
    ACT_SPEECH_STOP: SpeechStop,
    ACT_SPEECH_SPOKEN: SpokenAck,
    ACT_SPEECH_CHUNK: TtsChunk,
    ACT_SPEAKER_PCM: AudioOutFrame,
    ACT_SPEAKER_STOP: SpeakerStop,
    ACT_SPEAKER_STATE: SpeakerState,
    ACT_MOTOR_COMMAND: MotionCommand,
    ACT_LIGHT_SET: LightCommand,
    ACT_ESTOP_TRIGGER: EStop,
    ACT_TIMELINE_RUN: TimelineCommand,
    ACT_TIMELINE_PROGRESS: TimelineProgress,
    # /sys/ — framework traffic
    SYS_NODE_HEALTH: NodeHealth,
    SYS_NODE_META: NodeMeta,
    SYS_TRACE_STEP: TraceStep,
    SYS_GATE_DECISION: GateDecision,
    SYS_SKILL_XP_AWARDED: XpAwarded,
    SYS_SKILL_LEVEL_UP: SkillLevelUp,
    SYS_SKILL_UNLOCKED: SkillUnlocked,
    SYS_SKILL_MASTERED: SkillMastered,
}

#: Declared but deliberately unregistered — a name reserved for a
#: message that does not exist yet.  Anything NOT listed here and not in
#: the registry is an unregistered topic, which decodes to a KeyError
#: at runtime; ``test_topics.py`` fails the build over it.
RESERVED_TOPICS: frozenset[str] = frozenset({
    SENSE_VISION_ANALYSIS,      # inference output; no producer yet
})

ALL_TOPICS: tuple[str, ...] = tuple(TOPIC_TO_CLASS.keys())


def class_for_topic(topic: str) -> type[TopicMessage]:
    """Look up the msgspec.Struct subclass for a topic string.

    Resolves INSTANCE paths as well as registered ones: the contract
    registers a canonical path (no instance), and a live topic finds it
    by dropping its instance segment.

        /sense/camera/image_raw        <- registered, once
        /sense/camera/cam0/image_raw   <- resolves to the same class
        /sense/camera/cam1/image_raw   <- and so does this

    That is what lets an instance id be runtime data the contract has
    never seen, which is the whole reason a hierarchy is usable.

    Raises ``KeyError`` for genuinely unknown topics — call sites should
    treat that as schema drift, not a transient miss."""
    cls = TOPIC_TO_CLASS.get(topic)
    if cls is not None:
        return cls
    from jaeger_os.contract.paths import canonical
    canon = canonical(topic)
    if canon != topic:
        cls = TOPIC_TO_CLASS.get(canon)
        if cls is not None:
            return cls
    raise KeyError(topic)


__all__ = [
    # Constants — /sense/
    "SENSE_CAMERA_IMAGE_RAW", "SENSE_MIC_PCM", "SENSE_TOUCH_EVENT",
    "SENSE_PROPRIO_STATE", "SENSE_STT_TRANSCRIPT", "SENSE_STT_SPEECH_START",
    "SENSE_VISION_ANALYSIS",
    # Constants — /act/
    "ACT_DISPLAY_PLAY", "ACT_DISPLAY_STOP", "ACT_DISPLAY_FRAME",
    "ACT_DISPLAY_STATE", "ACT_DISPLAY_STATS",
    "ACT_SPEECH_SAY", "ACT_SPEECH_STOP", "ACT_SPEECH_SPOKEN",
    "ACT_SPEECH_CHUNK", "ACT_SPEAKER_PCM", "ACT_SPEAKER_STOP",
    "ACT_SPEAKER_STATE",
    "ACT_MOTOR_COMMAND", "ACT_LIGHT_SET", "ACT_ESTOP_TRIGGER",
    "ACT_TIMELINE_RUN", "ACT_TIMELINE_PROGRESS",
    # Constants — /sys/
    "SYS_NODE_HEALTH", "SYS_NODE_META", "SYS_TRACE_STEP", "SYS_GATE_DECISION",
    "SYS_SKILL_XP_AWARDED", "SYS_SKILL_LEVEL_UP", "SYS_SKILL_UNLOCKED",
    "SYS_SKILL_MASTERED",
    # Health severity
    "HEALTH_OK", "HEALTH_WARN", "HEALTH_ERROR", "HEALTH_STALE",
    "HEALTH_LEVELS",
    # Envelope + concrete types
    "TopicMessage", "FrameBuffer",
    "AudioInFrame", "Transcript", "UserSpeechStart", "CameraFrame",
    "TouchReading", "ProprioReading", "SpokenAck", "TtsChunk", "TraceStep",
    "GateDecision",
    "DisplayCommand", "DisplayStop", "DisplayFrame", "DisplayState",
    "DisplayStats",
    "SpeechCommand", "SpeechStop", "AudioOutFrame", "MotionCommand",
    "LightCommand", "EStop", "SpeakerStop", "SpeakerState",
    "TimelineCommand", "TimelineProgress",
    "NodeHealth", "NodeMeta",
    "XpAwarded", "SkillLevelUp", "SkillUnlocked", "SkillMastered",
    # Registry
    "TOPIC_TO_CLASS", "RESERVED_TOPICS", "ALL_TOPICS", "class_for_topic",
]
