"""Default skill-tree catalog — the starter tree every instance
gets so XP has somewhere to land + the operator's visualisation
later has a tree to render.

Categories
──────────
  animation   the L1-L4 adapter set vendored from Mochi (image,
              bitmap, sprite, gif, video, math), wired with
              prereq edges from the levels:
                image → bitmap → sprite → gif → video
                sprite → math
  voice       tts, stt, gate, lip-sync, barge-in (matches the
              0.4 shipped pieces)
  vision      camera_frame (the 0.4 base), inference (locked)
  motor       command, safety (both locked until JP01 wires)
  light       command (locked until JP01 wires)
  core        the existing tool surface (file IO, memory, web,
              calculate, schedule, time, weather) — retro-tagged
              at L1.  Tools call ``award_xp`` themselves on
              successful invocation; XpEmitter routes that to the
              registry.

This module is operator-friendly — adding a new skill is a
:func:`SkillNode` literal here.  Each entry is small and
declarative.

Usage::

    from jaeger_os.skill_tree import SkillTreeRegistry
    from jaeger_os.skill_tree.seed import seed_default_tree

    registry = SkillTreeRegistry.for_instance(layout)
    seed_default_tree(registry)
    registry.save()
"""

from __future__ import annotations

from .registry import SkillTreeRegistry
from .schema import SkillNode


# ── animation cluster ─────────────────────────────────────────────

_ANIMATION_NODES: tuple[SkillNode, ...] = (
    SkillNode(
        id="animation.image",
        name="Static image",
        description="L1 — display a single raster image (PNG, JPG, WebP).",
        category="animation",
        xp_to_mastery=200,
        unlocks=("animation.sprite", "animation.bitmap"),
    ),
    SkillNode(
        id="animation.bitmap",
        name="Bitmap (1-bit)",
        description="L1 — render packed 1-bit monochrome bitmaps.",
        category="animation",
        xp_to_mastery=200,
        unlocks=("animation.sprite",),
    ),
    SkillNode(
        id="animation.sprite",
        name="Sprite sheet",
        description="L2 — crop one sprite from a sheet, centred.",
        category="animation",
        prerequisites=("animation.image",),
        xp_to_mastery=300,
        unlocks=("animation.gif", "animation.math"),
    ),
    SkillNode(
        id="animation.gif",
        name="Animated GIF",
        description="L3 — loop animated GIF / APNG with per-frame timing.",
        category="animation",
        prerequisites=("animation.sprite",),
        xp_to_mastery=500,
        unlocks=("animation.video",),
    ),
    SkillNode(
        id="animation.video",
        name="Video clip",
        description="L4 — mp4 / webm clip playback.  Vendor pending.",
        category="animation",
        prerequisites=("animation.gif",),
        xp_to_mastery=1000,
        unlocks=("animation.rigged",),
    ),
    SkillNode(
        id="animation.math",
        name="Procedural / math",
        description=(
            "L4 — operator-authored Python scripts draw the frame "
            "(eye blinks, mouth shapes, idle micro-movements)."
        ),
        category="animation",
        prerequisites=("animation.sprite",),
        xp_to_mastery=1500,
        unlocks=("animation.generative",),
    ),
    SkillNode(
        id="animation.rigged",
        name="Rigged (Live2D / Spine)",
        description=(
            "L5 — deferred adapter slot.  Live2D Cubism or "
            "Esoteric Spine rigs."
        ),
        category="animation",
        prerequisites=("animation.video",),
        xp_to_mastery=5000,
        unlocks=("animation.generative",),
    ),
    SkillNode(
        id="animation.generative",
        name="Generative",
        description=(
            "L6 — deferred adapter slot.  Wan2.1 / SVD / NeRF "
            "real-time generation."
        ),
        category="animation",
        prerequisites=("animation.math", "animation.rigged"),
        xp_to_mastery=10_000,
    ),
)


# ── voice cluster ─────────────────────────────────────────────────

_VOICE_NODES: tuple[SkillNode, ...] = (
    SkillNode(
        id="voice.tts",
        name="Text to speech",
        description="Speak via Kokoro.  Shipped at 0.3+.",
        category="voice",
        xp_to_mastery=500,
    ),
    SkillNode(
        id="voice.stt",
        name="Speech to text",
        description="Whisper-based transcription.  Shipped at 0.3+.",
        category="voice",
        xp_to_mastery=500,
    ),
    SkillNode(
        id="voice.gate",
        name="Voice gate",
        description="Single-pass <ignore>/<reply> classifier.  Shipped at 0.4.",
        category="voice",
        prerequisites=("voice.stt",),
        xp_to_mastery=1000,
    ),
    SkillNode(
        id="voice.lip_sync",
        name="Lip sync",
        description=(
            "L1 — amplitude-driven mouth shape.  L2+ phoneme-aware "
            "is 0.6+ work."
        ),
        category="voice",
        prerequisites=("voice.tts", "animation.math"),
        xp_to_mastery=2000,
    ),
    SkillNode(
        id="voice.barge_in",
        name="Barge-in",
        description="User-speech-start during agent reply.  Shipped at 0.4.",
        category="voice",
        prerequisites=("voice.stt", "voice.tts"),
        xp_to_mastery=500,
    ),
)


# ── vision cluster ────────────────────────────────────────────────

_VISION_NODES: tuple[SkillNode, ...] = (
    SkillNode(
        id="vision.camera_frame",
        name="Camera frame capture",
        description="Raw frame capture; USB + TCP adapters.  Shipped at 0.4.",
        category="vision",
        xp_to_mastery=500,
    ),
    SkillNode(
        id="vision.analysis",
        name="Vision analysis",
        description="Object / scene inference.  Locked; future track.",
        category="vision",
        prerequisites=("vision.camera_frame",),
        xp_to_mastery=2000,
    ),
)


# ── motor / light clusters ────────────────────────────────────────

_MOTOR_NODES: tuple[SkillNode, ...] = (
    SkillNode(
        id="motor.command",
        name="Motion command",
        description="Velocity + waypoint motor command.  Locked until JP01 wires.",
        category="motor",
        xp_to_mastery=500,
    ),
    SkillNode(
        id="motor.safety",
        name="Motion safety reflex",
        description="Unconscious safety filter on motion commands.  Locked.",
        category="motor",
        prerequisites=("motor.command",),
        xp_to_mastery=2000,
    ),
)

_LIGHT_NODES: tuple[SkillNode, ...] = (
    SkillNode(
        id="light.command",
        name="LED command",
        description="RGB pattern playback.  Locked until JP01 wires.",
        category="light",
        xp_to_mastery=300,
    ),
)


# ── core tool surface (retro-documented at L1) ────────────────────

_CORE_NODES: tuple[SkillNode, ...] = (
    SkillNode(id="core.file_read", name="File read", category="core",
              xp_to_mastery=500),
    SkillNode(id="core.file_write", name="File write", category="core",
              xp_to_mastery=500),
    SkillNode(id="core.memory", name="Memory", category="core",
              xp_to_mastery=1000),
    SkillNode(id="core.calculate", name="Calculate", category="core",
              xp_to_mastery=200),
    SkillNode(id="core.web_search", name="Web search", category="core",
              xp_to_mastery=500),
    SkillNode(id="core.time", name="Time", category="core",
              xp_to_mastery=100),
    SkillNode(id="core.weather", name="Weather", category="core",
              xp_to_mastery=200),
    SkillNode(id="core.schedule", name="Schedule (cron)", category="core",
              xp_to_mastery=500),
)


_ALL_DEFAULT_NODES: tuple[SkillNode, ...] = (
    *_ANIMATION_NODES,
    *_VOICE_NODES,
    *_VISION_NODES,
    *_MOTOR_NODES,
    *_LIGHT_NODES,
    *_CORE_NODES,
)


def seed_default_tree(registry: SkillTreeRegistry) -> SkillTreeRegistry:
    """Register the default catalog on ``registry``, preserving any
    XP / level / status the registry already had for known IDs.
    Returns the registry for chaining."""
    for node in _ALL_DEFAULT_NODES:
        registry.register(node)
    return registry


def default_catalog() -> tuple[SkillNode, ...]:
    """Return the immutable default catalog tuple — useful for
    tests + future visualisation surfaces that want to enumerate
    "all known skills" without holding a registry."""
    return _ALL_DEFAULT_NODES
