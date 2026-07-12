"""Agent autonomy — how much it confirms mid-task, set like a permission mode.

The PLAN is agreed up front (we settle the task together); autonomy governs the
*execution* after that — specifically whether a tier-gated action pauses for a
prompt or runs on its own. Three modes:

  ask     — pause for approval before EVERY outward / hardware / destructive
            action (tiers 1-4). The strict, today-style gate.
  scoped  — agree the risky scope up front, then run autonomously within it: a
            standing "always" grant runs quiet, anything NEW prompts once (and
            "always" extends the scope). Out-of-scope or missing info → reach
            out via ``clarify``.   (the default)
  auto    — fully autonomous: auto-approve tiers 1-4 for an admin session; the
            agent only reaches out (``clarify``) when genuinely blocked.

tier-5 DEV_BYPASS still needs an explicit human override in every mode — it
never routes through this gate. Non-admin sessions are denied upstream, so this
only ever loosens things for the owner.

Switching is INSTANT — no model swap (unlike runtime ``modes``). State is
process-global (one resident agent per instance) and published as part of
:class:`ModeState` so the tray / chat header can show it.
"""

from __future__ import annotations

AUTONOMY = ("ask", "scoped", "auto")
DEFAULT = "scoped"

_DESC = {
    "ask": "pause for approval before every outward/hardware/destructive action",
    "scoped": "agree risky scope up front, then run autonomously within it; "
              "out-of-scope or missing info → ask",
    "auto": "fully autonomous; reach out only when genuinely blocked",
}

_state: dict[str, str] = {"mode": DEFAULT}


def current_autonomy() -> str:
    return _state["mode"]


def list_autonomy() -> list[str]:
    return list(AUTONOMY)


def autonomy_info() -> dict:
    """The CURRENT autonomy mode + options — what the agent reports when asked
    "will you ask before acting?" (answer from fact, never guess)."""
    m = _state["mode"]
    return {"autonomy": m, "options": list(AUTONOMY), "description": _DESC.get(m, "")}


def _publish(mode: str) -> None:
    try:
        from jaeger_ai.core.messages import ModeState
        from jaeger_ai.core.runtime import modes
        from jaeger_ai.main import _pipeline
        bus = _pipeline.get("chassis_bus")
        if bus is not None:
            bus.publish(ModeState(mode=modes.current_mode(), autonomy=mode))
    except Exception:  # noqa: BLE001 — status is best-effort
        pass


def set_autonomy(name: str) -> dict:
    """Switch the autonomy mode (instant, no model swap). Returns a status dict;
    never raises. No-op-safe if already in the target mode."""
    target = (name or "").strip().lower()
    if target not in AUTONOMY:
        return {"ok": False, "error": f"unknown autonomy {target!r}; choose from {list(AUTONOMY)}"}
    _state["mode"] = target
    _publish(target)
    return {"ok": True, "mode": target}
