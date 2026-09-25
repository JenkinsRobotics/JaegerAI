"""Topic paths — a hierarchy you can subscribe to at any level.

    /sense/camera/cam0/image_raw
     └cat─┘ └class┘ └inst┘ └─msg─┘

Subscribe to any prefix and the TRANSPORT filters for you:

    /sense/                     every input
    /sense/camera/              every camera
    /sense/camera/cam0/         just that one

That last property is the point. A flat namespace forces a consumer to
receive everything and discard what it does not want — free in-process,
but 81 MB/s of wasted link at 720p30 across a network. With a hierarchy
the broker never forwards it, because ZMQ SUB filtering is prefix-based
and subscriptions propagate upstream.

Two rules make it work:

**The instance id is STABLE and opaque.** ``cam0``, not ``left_camera``.
Human names ("left camera") live in the topology manifest and can be
changed freely, because nothing routes on them. This is where the design
deliberately departs from common ROS practice: putting a semantic name
in a topic means you can never rename the thing without breaking every
subscriber. JP01 already names controllers ``cc01``/``vcc01``/``mc01``
rather than "central"/"vision" — same instinct, one tier down.

**The last segment names the TYPE.** ``image_raw`` is what makes a path
decodable, so the instance segment can be runtime data the contract has
never seen. A canonical path (instance omitted) is what the contract
registers; a live path resolves to it by dropping the instance.
"""

from __future__ import annotations

from dataclasses import dataclass

SEP = "/"

#: Categories a path may start with. A closed set on purpose — an
#: unbounded vocabulary is how a namespace turns back into a flat one
#: with slashes in it.
#:
#: Only three, and the split is DIRECTION relative to the brain — the
#: same one the contract has used since 0.1. Direction is the one
#: property of a topic that never becomes debatable: a camera frame
#: flows in, a pixel buffer flows out, and no amount of argument moves
#: either. Every richer taxonomy we tried ("sensor" vs "sense" for raw
#: vs derived, "face" for rendered output) forces a judgement call at
#: each new topic and nothing routes on the answer.
CATEGORIES = (
    "sense",    # anything flowing IN: camera, mic, imu, range, touch,
                # and derived readings too (transcript, detections)
    "act",      # anything flowing OUT: motor, display, speaker, light,
                # estop. A display is an actuator that takes pixels the
                # way a motor is one that takes velocity.
    "sys",      # the framework's own traffic (health, meta, log)
)


class TopicPathError(ValueError):
    """A path that does not obey the grammar. Always says which rule."""


@dataclass(frozen=True)
class TopicPath:
    """A parsed topic path."""

    category: str
    cls: str
    message: str
    instance: str = ""      # "" for singleton topics

    def __str__(self) -> str:
        parts = [self.category, self.cls]
        if self.instance:
            parts.append(self.instance)
        parts.append(self.message)
        return SEP + SEP.join(parts)

    @property
    def canonical(self) -> str:
        """The same path with the instance removed.

        This is what the contract registers and what type resolution
        keys on, so one registration serves every instance.
        """
        return f"{SEP}{self.category}{SEP}{self.cls}{SEP}{self.message}"

    @property
    def prefix(self) -> str:
        """The subscribable prefix naming exactly this instance.

        Trailing separator on purpose: without it ``/sense/cam`` would
        prefix-match ``/sense/camera/...``, and a subscriber would
        silently receive a stream it never asked for.
        """
        if self.instance:
            return f"{SEP}{self.category}{SEP}{self.cls}{SEP}{self.instance}{SEP}"
        return f"{SEP}{self.category}{SEP}{self.cls}{SEP}"


def parse(path: str) -> TopicPath:
    """Parse a topic path. Raises :class:`TopicPathError` on any
    violation, naming the rule broken."""
    if not path.startswith(SEP):
        raise TopicPathError(f"topic must start with {SEP!r}: {path!r}")
    parts = [p for p in path.split(SEP) if p]
    if len(parts) == 3:
        category, cls, message = parts
        instance = ""
    elif len(parts) == 4:
        category, cls, instance, message = parts
    else:
        raise TopicPathError(
            f"topic must be /<category>/<class>/<message> or "
            f"/<category>/<class>/<instance>/<message>, got {path!r} "
            f"({len(parts)} segments)")
    if category not in CATEGORIES:
        raise TopicPathError(
            f"category {category!r} not in {CATEGORIES}: {path!r}")
    for name, value in (("class", cls), ("message", message)):
        if not value.replace("_", "").isalnum():
            raise TopicPathError(
                f"{name} segment {value!r} must be alphanumeric/underscore: "
                f"{path!r}")
    if instance and not instance.replace("_", "").replace("-", "").isalnum():
        raise TopicPathError(
            f"instance id {instance!r} must be alphanumeric/underscore/dash: "
            f"{path!r}")
    return TopicPath(category=category, cls=cls, message=message,
                     instance=instance)


def canonical(path: str) -> str:
    """Canonical (instance-free) form of ``path``.

    Falls back to the path unchanged when it does not parse, so callers
    holding a legacy flat topic keep working during migration rather
    than crashing on lookup.
    """
    try:
        return parse(path).canonical
    except TopicPathError:
        return path


def instance_of(path: str) -> str:
    """Instance id in ``path``, or "" for singletons / unparseable."""
    try:
        return parse(path).instance
    except TopicPathError:
        return ""


def for_instance(canonical_path: str, instance: str) -> str:
    """Build the live path for ``instance`` of a canonical topic.

        for_instance("/sense/camera/image_raw", "cam0")
        -> "/sense/camera/cam0/image_raw"
    """
    p = parse(canonical_path)
    if p.instance:
        raise TopicPathError(
            f"{canonical_path!r} already names instance {p.instance!r}")
    if not instance:
        return canonical_path
    return f"{SEP}{p.category}{SEP}{p.cls}{SEP}{instance}{SEP}{p.message}"


def matches(subscription: str, path: str) -> bool:
    """Does ``path`` fall under ``subscription``?

    Mirrors ZMQ SUB semantics (byte prefix) so the in-process bus and
    the ZMQ bus agree exactly. A subscription that is a full topic
    matches only itself; one ending in ``/`` matches everything beneath.
    """
    return path == subscription or path.startswith(subscription)


__all__ = ["SEP", "CATEGORIES", "TopicPath", "TopicPathError",
           "parse", "canonical", "instance_of", "for_instance", "matches"]
