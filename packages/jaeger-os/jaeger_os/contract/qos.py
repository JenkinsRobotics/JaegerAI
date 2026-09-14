"""Per-topic delivery policy — how much a subscriber may buffer, and
what happens when it cannot keep up.

Until this existed every topic got identical treatment: a 3.6 MB video
frame and a 200-byte e-stop shared one policy at one depth. That is
wrong in both directions. A dropped frame is fine — the next one is
along in 33 ms and it is more current anyway. A dropped e-stop is a
robot that does not stop.

Policy is CONTRACT-tier because it is a property of the topic, not of
whoever happens to subscribe. Two consumers of ``/act/estop/trigger`` must not
be able to disagree about whether it may be dropped.

Deliberately small: ``depth`` and ``reliability``. ROS's full QoS also
carries durability, deadline, liveliness and lifespan; none has a
consumer here yet, and a policy field nothing reads is spec ahead of
code.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Drop the oldest when a subscriber falls behind. Right for anything
#: where the newest value supersedes the old one — frames, telemetry,
#: sensor readings.
BEST_EFFORT = "best_effort"

#: Never drop silently. Buffers deeply and, on overflow, reports the
#: loss loudly instead of counting it quietly.
#:
#: HONEST LIMIT: this is not guaranteed delivery. Real reliability needs
#: acknowledgement and retransmission, which this bus does not do. What
#: it buys is a large buffer and an overflow you cannot miss — enough
#: for control messages on an in-process bus, not enough to claim
#: delivery over a lossy link.
RELIABLE = "reliable"

RELIABILITIES = (BEST_EFFORT, RELIABLE)


@dataclass(frozen=True)
class Qos:
    """Delivery policy for one topic."""

    depth: int = 64
    reliability: str = BEST_EFFORT

    def __post_init__(self) -> None:
        if self.depth < 1:
            raise ValueError(f"qos depth must be >= 1, got {self.depth}")
        if self.reliability not in RELIABILITIES:
            raise ValueError(
                f"qos reliability {self.reliability!r} not in {RELIABILITIES}")


#: What a topic gets when it declares nothing. Deep enough to absorb a
#: burst, shallow enough that a wedged subscriber cannot eat memory.
DEFAULT_QOS = Qos()

#: Topics whose delivery genuinely differs from the default.
#:
#: The two shapes worth naming:
#:
#: FRAMES get depth 2. A renderer that falls behind should show the
#: NEWEST frame, not work through a queue of stale ones — buffering 64
#: video frames is 230 MB of latency nobody wants to watch.
#:
#: STOP COMMANDS are reliable. These are the messages where dropping one
#: is a safety event rather than a dropped update.
TOPIC_QOS: dict[str, Qos] = {}


def _register(topic: str, qos: Qos) -> None:
    TOPIC_QOS[topic] = qos


def qos_for(topic: str) -> Qos:
    """Policy for ``topic``, falling back to :data:`DEFAULT_QOS`.

    Resolves INSTANCE paths through their canonical form, so every
    camera gets the camera policy and every display the display policy
    without the contract having to enumerate instances it cannot know.

    Without that fallback the failure is silent and backwards: an
    instanced frame topic would quietly take the 64-deep default
    instead of its depth-2 policy — 230 MB of stale frames buffered on
    a subscriber that stalled — and an instanced stop command would
    lose RELIABLE exactly where it matters.
    """
    q = TOPIC_QOS.get(topic)
    if q is not None:
        return q
    from jaeger_os.contract.paths import canonical
    canon = canonical(topic)
    if canon != topic:
        q = TOPIC_QOS.get(canon)
        if q is not None:
            return q
    return DEFAULT_QOS


def _install_defaults() -> None:
    """Populate the table from the topic constants.

    Imported lazily inside the function to avoid a circular import:
    ``topics`` is the wire truth and must not depend on policy, so the
    dependency runs this way round.
    """
    from jaeger_os.contract import topics as t

    # Safety and control — a lost one is not a lost update.
    for topic in (t.ACT_ESTOP_TRIGGER, t.ACT_SPEECH_STOP, t.ACT_DISPLAY_STOP,
                  t.ACT_SPEAKER_STOP):
        _register(topic, Qos(depth=256, reliability=RELIABLE))

    # Frames — newest wins, always.
    for topic in (t.ACT_DISPLAY_FRAME, t.ACT_DISPLAY_FRAME,
                  t.SENSE_CAMERA_IMAGE_RAW):
        _register(topic, Qos(depth=2))

    # Audio is a stream: a little buffering is normal, a lot is drift.
    for topic in (t.SENSE_MIC_PCM, t.ACT_SPEAKER_PCM):
        _register(topic, Qos(depth=16))


_install_defaults()

__all__ = ["Qos", "BEST_EFFORT", "RELIABLE", "RELIABILITIES",
           "DEFAULT_QOS", "TOPIC_QOS", "qos_for"]
