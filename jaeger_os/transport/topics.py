"""topics.py — single source of truth for JROS 0.4 node topics.

Pure schemas + constants.  No transport dependency.  Both the
in-process Bus (Track A.2) and the future ZMQ transport (Track A.5)
import from here.

Schemas are :class:`msgspec.Struct`, not Pydantic models — 10×
faster on the transport hot path AND native MessagePack support
for the binary topics (audio frames, vision frames).  Pydantic
stays in JROS for config validation + tool schemas where its
richer ecosystem earns the overhead; transport schemas live where
microseconds matter.  See ``dev/docs/ROADMAP_0.4.md`` open question
#2 (resolved): JSON for text topics, MessagePack for binary topics.

Namespace
---------
* ``/sense/*`` — inputs the brain reads (mic, STT output, vision,
  touch, encoders, TTS-done acks).
* ``/act/*``   — commands the brain writes (speech requests, audio
  frames bound for speakers, motor commands, LED commands).
* ``/health/*`` — reserved for the per-node liveness ticks
  (Track D); not declared here yet.

Adding a new topic
------------------
1. Add an ``UPPER_SNAKE_CASE`` constant.
2. Add a :class:`msgspec.Struct` subclass that inherits
   :class:`TopicMessage`, with
   ``topic: Literal[CONSTANT] = CONSTANT``.
3. Register it in :data:`TOPIC_TO_CLASS`.
4. Only bump ``topic_v`` (default 1) on breaking payload changes;
   add a migration note in the docstring.

The test suite enforces that every constant in :data:`ALL_TOPICS`
has a registered class, that subclasses pin their constant, and
that ``forbid_unknown_fields=True`` catches typos at decode time.
"""

from __future__ import annotations

import time
from typing import Literal

import msgspec


# ── topic name constants ──────────────────────────────────────────

SENSE_AUDIO_IN = "/sense/audio_in"
SENSE_TRANSCRIPT = "/sense/transcript"
SENSE_USER_SPEECH_START = "/sense/user_speech_start"
SENSE_GATE_DECISION = "/sense/gate_decision"
SENSE_CAMERA_FRAME = "/sense/camera_frame"
# Back-compat alias for code that still imports the old 0.4 draft name.
# Do not register this as a separate topic; raw frames live on
# /sense/camera_frame. Reserve /sense/vision_analysis for inference output.
SENSE_VISION = SENSE_CAMERA_FRAME
SENSE_VISION_ANALYSIS = "/sense/vision_analysis"
SENSE_TOUCH = "/sense/touch"
SENSE_PROPRIO = "/sense/proprio"
SENSE_SPOKEN = "/sense/spoken"
SENSE_TTS_CHUNK = "/sense/tts_chunk"
SENSE_TRACE_STEP = "/sense/trace_step"

ACT_SPEECH = "/act/speech"
ACT_AUDIO_OUT = "/act/audio_out"
ACT_MOTION = "/act/motion"
ACT_LIGHT = "/act/light"

# 0.5 — animation / timeline / skill-tree topics.
ACT_ANIMATION = "/act/animation"
ACT_TIMELINE = "/act/timeline"
SENSE_ANIMATION_STATE = "/sense/animation_state"
SENSE_TIMELINE_PROGRESS = "/sense/timeline_progress"
SENSE_XP_AWARDED = "/sense/xp_awarded"

# 0.5 — media node: a file → RGBA frames on the bus.  Local renderers
# (the floating media player) subscribe in-process; the same frames ride
# the ZMQ bus over TCP to a device node (e.g. a Jetson) for the
# upstream-render-on-Mac / downstream-display split.
ACT_MEDIA = "/act/media"
SENSE_MEDIA_FRAME = "/sense/media_frame"
SENSE_MEDIA_STATE = "/sense/media_state"
SENSE_SKILL_LEVEL_UP = "/sense/skill_level_up"
SENSE_SKILL_UNLOCKED = "/sense/skill_unlocked"
SENSE_SKILL_MASTERED = "/sense/skill_mastered"

# Control topics — interrupt / coordination commands ("stop /
# pause / resume what's in flight") rather than "do this action".
# Kept under ``/act/`` so the SUB-filter prefix at the brain side
# stays uniform; future control topics (mic_pause,
# stt_open_followup) will sit alongside.
ACT_SPEECH_STOP = "/act/speech_stop"
ACT_ANIMATION_STOP = "/act/animation_stop"


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
    topic: Literal["/sense/audio_in"] = SENSE_AUDIO_IN
    samples: bytes = b""  # float32 little-endian PCM
    sample_rate: int = 16000
    channels: int = 1


class Transcript(TopicMessage):
    """STT output for a finalized utterance."""
    topic: Literal["/sense/transcript"] = SENSE_TRANSCRIPT
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
    topic: Literal["/sense/user_speech_start"] = SENSE_USER_SPEECH_START


class GateDecision(TopicMessage):
    """Per-phrase decision the audio session's input pipeline made
    about whether to publish a transcript.

    Published by the audio session node for EVERY phrase that passes
    the STT stage — including ignored ones — so interfaces can
    render their voice-activity log (🤫 ignored / 🎙 accepted).
    Only ACCEPTED phrases also become a ``Transcript`` on
    ``/sense/transcript`` and reach the brain.

    Reason values:
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
    topic: Literal["/sense/gate_decision"] = SENSE_GATE_DECISION
    accepted: bool = False
    text: str = ""
    reason: str = ""


class CameraFrame(TopicMessage):
    """A single camera frame.  Binary payload — rides MessagePack
    on the wire so the encoded image bytes don't pay a base64 hop.

    Schema is intentionally lean: a camera node is a source, not
    an analyser.  No YOLO boxes, no scene descriptions, no
    detection metadata — those belong on a future
    ``/sense/vision_analysis`` topic published by a downstream
    inference node that consumes ``/sense/camera_frame``.

    Two source modes supported by the vision node (Track B.5):
        * USB camera (cv2.VideoCapture device index, local Mac)
        * TCP stream (frames pushed by a remote board over an
          Ethernet socket — today: JP01-VCC01 Jetson; tomorrow:
          any IP-streamable source)

    The brain doesn't care which mode produced a frame — same
    topic, same schema; only ``camera_id`` distinguishes sources
    when multiple cameras run at once.
    """
    topic: Literal["/sense/camera_frame"] = SENSE_CAMERA_FRAME
    image_w: int = 0
    image_h: int = 0
    encoding: str = "jpeg"  # "jpeg" | "png" | "raw_bgr8" | "raw_rgb8"
    frame_bytes: bytes = b""
    camera_id: str = "default"
    frame_seq: int = 0  # monotonic counter from the producing camera


class TouchReading(TopicMessage):
    """Contact-sensor reading from skin / bumpers."""
    topic: Literal["/sense/touch"] = SENSE_TOUCH
    sensor_id: str = ""
    in_contact: bool = False
    force_n: float = 0.0


class ProprioReading(TopicMessage):
    """Encoder + IMU state from JP01-MC01 (ESP32 motion controller)."""
    topic: Literal["/sense/proprio"] = SENSE_PROPRIO
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
    topic: Literal["/sense/spoken"] = SENSE_SPOKEN
    ok: bool = False
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
    topic: Literal["/sense/tts_chunk"] = SENSE_TTS_CHUNK
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
    topic: Literal["/sense/trace_step"] = SENSE_TRACE_STEP
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
    match against the :class:`SpokenAck` reply (the tool-RPC
    pattern)."""
    topic: Literal["/act/speech"] = ACT_SPEECH
    text: str = ""
    voice: str = "af_heart"
    rate: float = 1.0  # 1.0 = normal speed


class AudioOutFrame(TopicMessage):
    """Synthesized audio frames bound for the speaker.  Binary
    payload; published by the tts node, consumed by audio_out."""
    topic: Literal["/act/audio_out"] = ACT_AUDIO_OUT
    samples: bytes = b""  # float32 little-endian PCM
    sample_rate: int = 24000
    channels: int = 1


ACT_ESTOP = "/act/estop"
SENSE_NODE_HEALTH = "/sense/node_health"


class EStop(TopicMessage):
    """System e-stop — L2 of the hardware safety contract (see
    dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md §2.8). Publishing with
    ``engaged=True`` LATCHES the stop: every hardware node in the
    package's ``safety.estop_scope`` executes its node-local stop on
    receipt, and motion capabilities refuse while latched. Release
    (``engaged=False``) is an explicit operator action — the framework
    never auto-releases."""
    topic: Literal["/act/estop"] = ACT_ESTOP
    engaged: bool = True
    reason: str = ""
    source: str = ""   # "operator" / "agent" / "button" / "supervisor"


class NodeHealth(TopicMessage):
    """Periodic node liveness heartbeat. ``state`` mirrors
    ``jaeger_os.nodes.base.NodeState`` values; ``link_connected`` and
    ``last_controller_rx_age_s`` describe the hardware link when the
    node owns one (0-default = not applicable)."""
    topic: Literal["/sense/node_health"] = SENSE_NODE_HEALTH
    node: str = ""
    state: str = ""
    link_connected: bool = False
    last_controller_rx_age_s: float = 0.0
    detail: str = ""


class MotionCommand(TopicMessage):
    """Brain → motor_ctrl (JP01-MC01 ESP32): motion command.

    Two complementary modes:
        * velocity — set ``linear_*``/``angular_z``, held for
          ``duration_s`` seconds.
        * waypoint — set ``use_waypoint=True`` and ``target_xy`` to
          [x, y] in metres (frame TBD by motor_ctrl).
    """
    topic: Literal["/act/motion"] = ACT_MOTION
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
    topic: Literal["/act/speech_stop"] = ACT_SPEECH_STOP
    reason: str = "interrupted"


class LightCommand(TopicMessage):
    """Brain → led_ctrl (JP01-AVC01 Teensy): RGB LED state.

    ``rgb`` is a list of 3 ints in [0, 255].  ``pattern`` is the
    playback shape; "solid" holds the colour, "pulse"/"rainbow"
    animate, "off" blanks the strip.  ``duration_ms=0`` means hold
    until the next command."""
    topic: Literal["/act/light"] = ACT_LIGHT
    strip_id: str = "default"
    rgb: list[int] = msgspec.field(default_factory=lambda: [0, 0, 0])
    pattern: str = "solid"  # "solid" | "pulse" | "rainbow" | "off"
    duration_ms: int = 0


# ── 0.5 animation / timeline / skill-tree ──────────────────────────

class AnimationCommand(TopicMessage):
    """Brain → animation_node: play an animation clip.

    The ``adapter`` field names which Mochi-vendored adapter handles
    rendering (image/bitmap/sprite/gif/video/math).  ``asset_path``
    is relative to the active instance's ``avatar/`` directory.
    ``params`` carries adapter-specific options (fit_mode, loop,
    speed, etc.).  ``duration_ms=0`` means play to natural end
    (image: hold; gif: one loop pass; video: full duration).

    Mochi parity: ImageHandler, GifHandler, etc.  See
    dev/docs/library_review/mochi_demo.md for the vendoring map."""
    topic: Literal["/act/animation"] = ACT_ANIMATION
    adapter: str = "image"
    asset_path: str = ""
    duration_ms: int = 0
    params: dict = msgspec.field(default_factory=dict)


class AnimationStop(TopicMessage):
    """Stop the currently playing animation; revert to idle/default."""
    topic: Literal["/act/animation_stop"] = ACT_ANIMATION_STOP


class MediaCommand(TopicMessage):
    """Brain / Studio → media_node: play a file (image / gif / video).  The
    node decodes it to RGBA frames streamed as ``MediaFrame``.  ``loop``
    repeats gif/video; an image is a single held frame.  A new command
    preempts the current clip."""
    topic: Literal["/act/media"] = ACT_MEDIA
    path: str = ""
    loop: bool = True


class MediaFrame(TopicMessage):
    """media_node → renderer: one RGBA8 frame (``width*height*4`` bytes).
    The floating media player subscribes in-process; the same frame rides
    the ZMQ bus over TCP to a device node (e.g. a Jetson)."""
    topic: Literal["/sense/media_frame"] = SENSE_MEDIA_FRAME
    data: bytes = b""
    width: int = 0
    height: int = 0


class MediaState(TopicMessage):
    """media_node → surfaces: playback state for the current clip."""
    topic: Literal["/sense/media_state"] = SENSE_MEDIA_STATE
    path: str = ""
    kind: str = ""
    playing: bool = False
    reason: str = "interrupted"


class TimelineCommand(TopicMessage):
    """Brain → animation_node + tts_node + motor_node: play a
    multi-track timeline (greeting, performance, scripted sequence).

    The timeline body is a JSON-serialised OTIO-shaped dict carried
    inline OR a name resolved against ``<instance>/timelines/*.json``.
    Bus consumers (animation node for animation tracks, tts node for
    speech tracks, etc.) extract their relevant track and schedule
    its events.

    See dev/docs/0.5.0_timeline_schema.md for the schema."""
    topic: Literal["/act/timeline"] = ACT_TIMELINE
    name: str = ""                # named timeline from instance dir; "" → inline
    timeline_json: str = ""       # serialised when inline
    loop: bool = False


class AnimationState(TopicMessage):
    """Animation node → bus: current state for the operator / UI /
    visualisation to observe."""
    topic: Literal["/sense/animation_state"] = SENSE_ANIMATION_STATE
    adapter: str = ""
    asset_path: str = ""
    state: str = "idle"           # "idle" | "playing" | "stopping"
    progress: float = 0.0         # 0..1 within current asset
    elapsed_ms: int = 0


class TimelineProgress(TopicMessage):
    """Animation node / timeline runner → bus: timeline scheduling
    progress.  Lets the brain know when scripted sequences finish."""
    topic: Literal["/sense/timeline_progress"] = SENSE_TIMELINE_PROGRESS
    timeline_name: str = ""
    state: str = "running"        # "running" | "complete" | "interrupted"
    elapsed_ms: int = 0
    duration_ms: int = 0


class XpAwarded(TopicMessage):
    """Skill-tree XP grant event.  Emitted by ``xp_emitter`` whenever
    a tool dispatch / bench pass / milestone awards XP to a skill.
    Subscribers: the skill_tree registry (which persists state), and
    eventual visualisation surfaces.

    See dev/docs/SKILL_TREE.md for the XP-progression contract."""
    topic: Literal["/sense/xp_awarded"] = SENSE_XP_AWARDED
    skill_id: str = ""
    amount: int = 0
    reason: str = ""
    metadata: dict = msgspec.field(default_factory=dict)


class SkillLevelUp(TopicMessage):
    """Skill-tree level-up event.  Fired by the registry when a skill
    crosses its xp_to_next_level threshold."""
    topic: Literal["/sense/skill_level_up"] = SENSE_SKILL_LEVEL_UP
    skill_id: str = ""
    new_level: int = 0


class SkillUnlocked(TopicMessage):
    """Skill-tree unlock event.  Fired when a skill's prerequisites
    are all satisfied, transitioning it from ``locked`` →
    ``available``."""
    topic: Literal["/sense/skill_unlocked"] = SENSE_SKILL_UNLOCKED
    skill_id: str = ""


class SkillMastered(TopicMessage):
    """Skill-tree mastery event.  Fired when XP crosses xp_to_mastery."""
    topic: Literal["/sense/skill_mastered"] = SENSE_SKILL_MASTERED
    skill_id: str = ""


# ── registry + lookup ─────────────────────────────────────────────

TOPIC_TO_CLASS: dict[str, type[TopicMessage]] = {
    SENSE_AUDIO_IN: AudioInFrame,
    SENSE_TRANSCRIPT: Transcript,
    SENSE_USER_SPEECH_START: UserSpeechStart,
    SENSE_GATE_DECISION: GateDecision,
    SENSE_CAMERA_FRAME: CameraFrame,
    SENSE_TOUCH: TouchReading,
    SENSE_PROPRIO: ProprioReading,
    SENSE_SPOKEN: SpokenAck,
    SENSE_ANIMATION_STATE: AnimationState,
    SENSE_TIMELINE_PROGRESS: TimelineProgress,
    SENSE_XP_AWARDED: XpAwarded,
    SENSE_SKILL_LEVEL_UP: SkillLevelUp,
    SENSE_SKILL_UNLOCKED: SkillUnlocked,
    SENSE_SKILL_MASTERED: SkillMastered,
    ACT_SPEECH: SpeechCommand,
    ACT_AUDIO_OUT: AudioOutFrame,
    ACT_MOTION: MotionCommand,
    ACT_LIGHT: LightCommand,
    ACT_ANIMATION: AnimationCommand,
    ACT_ANIMATION_STOP: AnimationStop,
    ACT_TIMELINE: TimelineCommand,
    ACT_SPEECH_STOP: SpeechStop,
    ACT_ESTOP: EStop,
    SENSE_NODE_HEALTH: NodeHealth,
    SENSE_TRACE_STEP: TraceStep,
    ACT_MEDIA: MediaCommand,
    SENSE_MEDIA_FRAME: MediaFrame,
    SENSE_MEDIA_STATE: MediaState,
}

ALL_TOPICS: tuple[str, ...] = tuple(TOPIC_TO_CLASS.keys())


def class_for_topic(topic: str) -> type[TopicMessage]:
    """Look up the msgspec.Struct subclass for a topic string.

    Raises ``KeyError`` for unknown topics — call sites should treat
    this as a hard error (an unknown topic indicates schema drift,
    not a transient miss)."""
    return TOPIC_TO_CLASS[topic]


__all__ = [
    # Constants
    "SENSE_AUDIO_IN", "SENSE_TRANSCRIPT", "SENSE_USER_SPEECH_START",
    "SENSE_CAMERA_FRAME", "SENSE_VISION", "SENSE_VISION_ANALYSIS",
    "SENSE_TOUCH", "SENSE_PROPRIO", "SENSE_SPOKEN",
    "ACT_SPEECH", "ACT_AUDIO_OUT", "ACT_MOTION", "ACT_LIGHT",
    "ACT_SPEECH_STOP", "ACT_ESTOP", "SENSE_NODE_HEALTH",
    "ALL_TOPICS",
    # Envelope + concrete types
    "TopicMessage",
    "AudioInFrame", "Transcript", "UserSpeechStart", "CameraFrame",
    "TouchReading", "ProprioReading", "SpokenAck",
    "SpeechCommand", "AudioOutFrame", "MotionCommand", "LightCommand",
    "SpeechStop", "EStop", "NodeHealth",
    # Registry
    "TOPIC_TO_CLASS", "class_for_topic",
]
