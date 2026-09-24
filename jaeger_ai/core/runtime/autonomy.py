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
            (the default of the saved instance setting the Gateway follows: it is the
            operator's own assistant on their own machine)

tier-5 DEV_BYPASS still needs an explicit human override in every mode — it
never routes through this gate. Non-admin sessions are denied upstream, so this
only ever loosens things for the owner.

Switching is INSTANT — no model swap (unlike runtime ``modes``). State is
process-global (one resident agent per instance) and published as part of
:class:`ModeState` so the tray / chat header can show it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

AUTONOMY = ("ask", "scoped", "auto")
DEFAULT = "scoped"
CONFIG_DEFAULT = "auto"
"""The saved ``automation.autonomy`` default the Gateway follows: the operator's own
assistant on their own machine, so no approval prompts. ``DEFAULT`` is only the
in-process starting mode for the legacy terminal/bridge providers."""

_DESC = {
    "ask": "pause for approval before every outward/hardware/destructive action",
    "scoped": "agree risky scope up front, then run autonomously within it; "
              "out-of-scope or missing info → ask",
    "auto": "fully autonomous; reach out only when genuinely blocked",
}

_state: dict[str, Any] = {"mode": DEFAULT, "explicit": False}


def current_autonomy() -> str:
    return _state["mode"]


def configured_autonomy(config_path: Path | str | None) -> str:
    """The instance's saved ``automation.autonomy`` (default when absent or invalid)."""
    try:
        import yaml

        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        value = str((raw.get("automation") or {}).get("autonomy") or "").strip().lower()
        return value if value in AUTONOMY else CONFIG_DEFAULT
    except Exception:  # noqa: BLE001 — no readable config means the default
        return CONFIG_DEFAULT


def effective_autonomy(config_path: Path | str | None = None) -> str:
    """What governs approvals now: an explicit runtime switch, else the saved setting."""
    if _state["explicit"]:
        return _state["mode"]
    return configured_autonomy(config_path) if config_path else _state["mode"]


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
    _state["explicit"] = True
    _publish(target)
    return {"ok": True, "mode": target}
