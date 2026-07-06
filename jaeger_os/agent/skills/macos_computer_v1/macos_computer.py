"""Agent-facing tools for the macos_computer skill.

Three tools the model sees — every engine-level primitive stays
hidden so the routing surface is tight:

  * ``computer_do(goal)``    — the high-level entry point. Accepts a
    plain-string goal (planner decomposes via current heuristics)
    OR a list of action dicts (model already decided the steps).
  * ``computer_use(action)`` — explicit primitive when the model
    wants to skip planning and dispatch one action directly.
  * ``computer_look()``      — current screen state. Cheap: returns
    the frontmost app, window list, and the focused window's AX
    summary. Optional ``include_screenshot=True`` for a one-shot
    visual.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.agent.skills.macos_computer_v1.engines import Action
from jaeger_os.agent.skills.macos_computer_v1 import planner
from jaeger_os.agent.skills.macos_computer_v1.goal_parser import parse_goal


def computer_do(goal: Any) -> dict:
    """High-level computer control. Accepts either:

      * ``goal`` as a plain string ("open Calculator and add 5+5")
        — the model is expected to decompose into action dicts in
        the SAME turn before calling, or the planner will treat
        the string as a single ``"goal"`` action and fall through
        to vision. (A future planner pass adds string→steps.)
      * ``goal`` as a list of action dicts —
        ``[{kind, args, target?}, ...]``. Each is dispatched
        through the capability ladder; on ``ok=False`` the planner
        tries the next-best engine. Stops at the first failure
        that no engine recovers.

    Returns ``{ok, steps: [...], halt_reason?, wall_ms}``. Each
    step dict carries which engine handled it for audit-logging."""
    steps_in: list[Action]
    if isinstance(goal, list):
        steps_in = [_to_action(s) for s in goal if isinstance(s, dict)]
    elif isinstance(goal, dict):
        steps_in = [_to_action(goal)]
    else:
        # String goal — run through the heuristic parser. Returns
        # one action per recognised clause, or a single ``"goal"``
        # action on unrecognised input (no engine claims it, the
        # agent sees a clean "decompose explicitly" message).
        steps_in = parse_goal(str(goal))

    if not steps_in:
        return {"ok": False, "error": "empty plan — pass either a string "
                                       "goal or a list of action dicts"}

    out_steps: list[dict] = []
    overall_ok = True
    halt_reason = ""
    import time
    started = time.perf_counter()
    for action in steps_in:
        result = planner.run(action)
        out_steps.append({
            "kind": action.kind,
            "target": action.target,
            **{k: v for k, v in result.items() if k != "attempts"},
            "attempts": result.get("attempts", []),
        })
        if not result.get("ok"):
            overall_ok = False
            halt_reason = result.get("error", "step failed")
            break
    return {
        "ok": overall_ok,
        "steps": out_steps,
        "wall_ms": round((time.perf_counter() - started) * 1000.0, 1),
        **({"halt_reason": halt_reason} if halt_reason else {}),
    }


def computer_use(action: str, target: str = "", **args: Any) -> dict:
    """Dispatch ONE action through the capability ladder.

    ``action`` is the kind (``"press"``, ``"open_url"``,
    ``"move_window"``, ``"click_xy"``, …). ``target`` is the
    canonical hint (app name, URL, element label). Remaining
    keyword args go into the action's ``args`` dict so each
    engine sees a uniform shape.

    Returns the engine's ``EngineResult`` plus the ladder's audit
    log."""
    act = Action(kind=str(action or "").strip(),
                 args=dict(args), target=str(target or "").strip())
    if not act.kind:
        return {"ok": False, "error": "empty action kind"}
    return planner.run(act)


def computer_look(app: str = "", include_screenshot: bool = False) -> dict:
    """Cheap snapshot of the screen state. Read-only — no focus
    changes, no clicks.

    Returns:
      * ``apps`` — every UI app currently running (name, bundle, pid)
      * ``focused`` — the focused window: title, position, size,
        + shallow summary of its children (roles, titles, first 80
        chars of each value). When ``app`` is given, the focused
        window OF THAT APP; otherwise the system-wide focused
        window.
      * ``screenshot`` — only when ``include_screenshot=True``.
        Adds a one-shot PNG path via the vision engine.

    The focused-window summary is the verification path after a
    click/type — much cheaper than a screenshot, and usually
    carries the exact value the agent wants to confirm."""
    out: dict[str, Any] = {"ok": True}

    # Running apps — quick inventory.
    apps_result = planner.run(Action(kind="list_apps", args={}, target=""))
    out["apps"] = apps_result.get("result") if apps_result.get("ok") else None

    # Focused window + shallow children — the cheap verification path.
    focus_result = planner.run(Action(
        kind="focused_window", args={}, target=app,
    ))
    out["focused"] = focus_result.get("result") if focus_result.get("ok") else None

    if include_screenshot:
        shot = planner.run(Action(
            kind="screenshot", args={}, target="",
        ))
        out["screenshot"] = shot.get("result", {}) if shot.get("ok") else None
    return out


# ── helpers ─────────────────────────────────────────────────────


def _to_action(d: dict) -> Action:
    """Coerce a dict into an :class:`Action`. Tolerant of common
    naming (``"action"``/``"kind"`` for the verb, ``"app"`` /
    ``"url"`` as targets, ``"args"`` or inline keys)."""
    kind = str(d.get("kind") or d.get("action") or "").strip()
    target = str(d.get("target") or d.get("app") or d.get("url") or "").strip()
    args = dict(d.get("args") or {})
    # Fold inline keys that aren't reserved into args.
    for k, v in d.items():
        if k in ("kind", "action", "target", "app", "url", "args"):
            continue
        args.setdefault(k, v)
    return Action(kind=kind, args=args, target=target)


def register(host: Any) -> None:
    """Skill entry point — register the three model-visible tools
    on the agent's tool registry.

    See ``SKILL.md`` for the design contract. The skill loader
    calls this with the host's registry-binding object once the
    skill's smoke tests pass."""
    import sys
    from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
    from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

    # The registered tools share their names with the module-level
    # implementations they delegate to; reach the impls through the module
    # object so the local defs below don't shadow (or recurse into) them.
    _impl = sys.modules[__name__]

    @register_tool_from_function
    @requires_tier(
        PermissionTier.EXTERNAL_EFFECT,
        skill="macos_computer", operation="computer_do",
        summary="drive macOS UI through the capability ladder",
    )
    def computer_do(goal: Any) -> dict:
        """Run a plan (string or list of action dicts) through the
        AppleScript → browser → AX → vision capability ladder.
        Picks the fastest available engine per step. Tier-2."""
        return _impl.computer_do(goal)

    @register_tool_from_function
    @requires_tier(
        PermissionTier.EXTERNAL_EFFECT,
        skill="macos_computer", operation="computer_use",
        summary="dispatch one computer action through the ladder",
    )
    def computer_use(action: str, target: str = "", **kwargs: Any) -> dict:
        """Dispatch ONE action through the capability ladder. Kind
        examples: press / open_url / move_window / click_xy. Tier-2."""
        return _impl.computer_use(action=action, target=target, **kwargs)

    @register_tool_from_function
    def computer_look(app: str = "", include_screenshot: bool = False) -> dict:
        """Read-only snapshot — running apps + the focused window
        (title / position / size / shallow child summary).
        ``app=...`` returns the focused window OF THAT APP;
        ``include_screenshot=True`` adds a one-shot PNG path. Read-
        only, no clicks."""
        return _impl.computer_look(app=app, include_screenshot=include_screenshot)


__all__ = [
    "computer_do",
    "computer_use",
    "computer_look",
    "register",
]
