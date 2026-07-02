"""Avatar tools — the brain's entry points for driving the face.

  • set_avatar_state(emotion=, hold_ms=)  — switch face expression
  • play_timeline(name=)                  — fire a multi-track sequence
  • warm_avatar()                         — preload AnimationNode at boot

0.5 wiring: same shape as ``speak.py`` — publish on the bus, optionally
wait for an ack, return a dict matching the agent's tool surface
convention.  Per operator-locked contract: "**a tool does the
networking, the node does the execution.**"

Path sandboxing
----------------
``play_timeline``'s ``name=`` argument is resolved under
``<instance>/timelines/`` via the standard sandbox helper.  Operator
content stays in the user bucket; framework code never sees
operator paths directly.

Skill-tree XP
-------------
Each successful invocation awards XP to the matching skill
(``animation.image`` for emotion → image, ``animation.math`` for
procedural, etc.) — wired through ``skill_tree.award_xp``.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from jaeger_os.core.context import SandboxError, _require_layout, _resolve_under


# ── default emotion → adapter+asset mapping ─────────────────────────
#
# Hardcoded defaults so set_avatar_state works out of the box.
# Operators can override per-instance by dropping a JSON file at
# ``<instance>/avatar/expressions.json`` with the same shape:
#
#     {
#       "neutral":  {"adapter": "image", "asset": "neutral.png"},
#       "happy":    {"adapter": "image", "asset": "happy.png"},
#       ...
#     }
#
# When the per-instance file exists it WINS — defaults are just the
# safety net so the tool never fails on a fresh instance.
_DEFAULT_EXPRESSIONS: dict[str, dict[str, Any]] = {
    "neutral":   {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "neutral"}},
    "happy":     {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "happy"}},
    "sad":       {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "sad"}},
    "focused":   {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "focused"}},
    "thinking":  {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "thinking"}},
    "speaking":  {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "speaking"}},
    "listening": {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "listening"}},
}


# Framework default face scripts ship under this path.  The avatar
# tool falls back here when the instance's ``avatar/`` directory
# doesn't contain the asset — so a fresh instance has a working
# face out of the box without the wizard having to copy files.
_FRAMEWORK_AVATAR_DEFAULTS = (
    Path(__file__).resolve().parent.parent  # agent/
    / "personas" / "lilith" / "avatar"
)


# Timeout for the optional ack wait (when ``wait=True``).  Most
# callers won't wait — they just fire-and-forget so the brain can
# continue.
_ACK_TIMEOUT_S = 2.0


# ── warm_avatar ─────────────────────────────────────────────────────

def warm_avatar() -> dict[str, Any]:
    """Pre-spin the AnimationNode + FrameBridge so the first
    ``set_avatar_state`` call doesn't pay startup overhead.

    Called from ``main.py``'s prewarm pass when ``config.avatar.enabled``
    is true.
    """
    from jaeger_os.nodes import runtime
    try:
        runtime.ensure_animation_node()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}
    return {"ok": True}


# ── set_avatar_state ────────────────────────────────────────────────

def set_avatar_state(
    emotion: str = "neutral",
    hold_ms: int = 0,
    wait: bool = False,
) -> dict[str, Any]:
    """Switch the avatar's face to ``emotion``.

    Args:
      emotion:  one of "neutral", "happy", "sad", "focused",
                "thinking", "speaking", "listening" — operator can
                add more via ``<instance>/avatar/expressions.json``.
      hold_ms:  how long to hold the new state (0 = until replaced).
      wait:     if True, blocks until the node acknowledges via
                ``/sense/animation_state``; default False = fire
                and forget (recommended — keeps the brain's loop
                snappy).

    Returns:
      ``{"ok": bool, "emotion": str, "adapter": str, "asset": str,
         "reason": str | None}``
    """
    layout = _require_layout()
    mapping = _resolve_expression(emotion, layout)
    if mapping is None:
        return {
            "ok": False,
            "emotion": emotion,
            "reason": f"unknown emotion: {emotion!r}",
        }

    # Resolve the asset.  Prefer the instance's <instance>/avatar/
    # if the operator has authored their own; fall back to the
    # framework defaults shipped with the lilith persona.  Both
    # paths are sandbox-checked.
    asset_rel = mapping["asset"]
    avatar_dir = layout.root / "avatar"
    try:
        instance_path = _resolve_under(avatar_dir, asset_rel)
    except SandboxError as exc:
        return {
            "ok": False,
            "emotion": emotion,
            "reason": f"asset outside sandbox: {exc}",
        }

    if instance_path.exists():
        resolved_path = str(instance_path)
    else:
        # Framework default — already under the package; no
        # sandbox check needed (this is framework code, not
        # operator-writable).
        fallback = _FRAMEWORK_AVATAR_DEFAULTS / asset_rel
        if fallback.exists():
            resolved_path = str(fallback)
        else:
            resolved_path = str(instance_path)  # let the node report missing

    return _publish_animation(
        adapter=mapping["adapter"],
        asset_path=resolved_path,
        duration_ms=int(hold_ms),
        emotion=emotion,
        params=mapping.get("params", {}),
        wait=wait,
    )


# ── play_timeline ───────────────────────────────────────────────────

def play_timeline(
    name: str = "",
    wait: bool = False,
) -> dict[str, Any]:
    """Play a multi-track timeline stored at
    ``<instance>/timelines/<name>.json``.

    Args:
      name:  timeline file basename (no .json suffix); resolved
             under ``<instance>/timelines/``.
      wait:  if True, block until the timeline completes via
             ``/sense/timeline_progress``; default False = run in
             the background.

    Returns:
      ``{"ok": bool, "name": str, "duration_ms": int,
         "reason": str | None}``
    """
    target = (name or "").strip()
    if not target:
        return {"ok": False, "name": "", "reason": "name required"}

    layout = _require_layout()
    timelines_dir = layout.root / "timelines"
    try:
        path = _resolve_under(
            timelines_dir,
            target if target.endswith(".json") else f"{target}.json",
        )
    except SandboxError as exc:
        return {
            "ok": False,
            "name": target,
            "reason": f"timeline path outside sandbox: {exc}",
        }
    if not path.exists():
        return {
            "ok": False,
            "name": target,
            "reason": f"timeline file not found: {path}",
        }

    try:
        from jaeger_os.timeline import parse_timeline_json
        timeline = parse_timeline_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "name": target,
            "reason": f"invalid timeline JSON: {exc}",
        }

    from jaeger_os.timeline import TimelineRunner
    from jaeger_os.nodes import runtime
    bus = runtime.get_bus()

    runner = TimelineRunner(bus, timeline)
    runner.start()

    if wait:
        duration_s = max(
            timeline.computed_duration_ms() / 1000.0 + 1.0,
            5.0,
        )
        finished = runner.wait(timeout=duration_s)
        if not finished:
            runner.stop()
            return {
                "ok": False,
                "name": target,
                "reason": "timeline runner timeout",
            }
        return {
            "ok": runner.final_state == "complete",
            "name": target,
            "duration_ms": timeline.computed_duration_ms(),
            "final_state": runner.final_state,
        }

    return {
        "ok": True,
        "name": target,
        "duration_ms": timeline.computed_duration_ms(),
        "final_state": "running",
    }


# ── helpers ─────────────────────────────────────────────────────────

def _resolve_expression(emotion: str, layout) -> dict[str, str] | None:
    """Look up emotion → {adapter, asset}.  Per-instance overrides win
    over the framework defaults."""
    overrides_path = layout.root / "avatar" / "expressions.json"
    if overrides_path.exists():
        try:
            overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
            if isinstance(overrides, dict) and emotion in overrides:
                entry = overrides[emotion]
                if (isinstance(entry, dict)
                        and "adapter" in entry and "asset" in entry):
                    return entry
        except Exception:  # noqa: BLE001
            pass
    return _DEFAULT_EXPRESSIONS.get(emotion)


def _publish_animation(
    *,
    adapter: str,
    asset_path: str,
    duration_ms: int,
    emotion: str,
    params: dict | None = None,
    wait: bool,
) -> dict[str, Any]:
    """Publish an :class:`AnimationCommand` on the bus.  If ``wait``,
    block briefly on the matching :class:`AnimationState` event."""
    from jaeger_os.transport import topics
    from jaeger_os.nodes import runtime

    runtime.ensure_animation_node()
    bus = runtime.get_bus()

    cid = uuid.uuid4().hex
    cmd = topics.AnimationCommand(
        adapter=adapter,
        asset_path=asset_path,
        duration_ms=duration_ms,
        params=dict(params or {}),
        node_id="brain",
        correlation_id=cid,
    )

    if not wait:
        try:
            bus.publish(cmd)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "emotion": emotion,
                "adapter": adapter,
                "asset": asset_path,
                "reason": str(exc),
            }
        return {
            "ok": True,
            "emotion": emotion,
            "adapter": adapter,
            "asset": asset_path,
        }

    try:
        ack = bus.request(
            cmd,
            ack_topic=topics.SENSE_ANIMATION_STATE,
            timeout_s=_ACK_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "emotion": emotion,
            "adapter": adapter,
            "asset": asset_path,
            "reason": str(exc),
        }
    if ack is None:
        return {
            "ok": False,
            "emotion": emotion,
            "adapter": adapter,
            "asset": asset_path,
            "reason": f"animation node timeout after {_ACK_TIMEOUT_S}s",
        }
    return {
        "ok": True,
        "emotion": emotion,
        "adapter": adapter,
        "asset": asset_path,
        "node_state": getattr(ack, "state", ""),
    }
