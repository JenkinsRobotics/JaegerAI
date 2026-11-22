"""Agent autonomy — how much it confirms mid-task, set like a permission mode.

The PLAN is agreed up front (we settle the task together); autonomy governs the
*execution* after that — specifically whether a tier-gated action pauses for a
prompt or runs on its own. Four modes:

  ask     — pause for approval before EVERY outward / hardware / destructive
            action (tiers 1-4). The strict, today-style gate.
  scoped  — agree the risky scope up front, then run autonomously within it: a
            standing "always" grant runs quiet, anything NEW prompts once (and
            "always" extends the scope). Out-of-scope or missing info → reach
            out via ``clarify``.   (the default)
  auto    — automatically approve permitted actions while retaining Jaeger's
            normal workspace and process sandbox.
  full    — Full access: the authenticated owner authorizes unrestricted local
            execution. Jaeger's approval, sandbox, deny-rule, protected-target,
            and destructive-action gates are bypassed; only the host OS and
            underlying tool capabilities remain authoritative.

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

AUTONOMY = ("ask", "scoped", "auto", "full")
AUTONOMY_ALIASES: dict[str, str] = {
    "ask": "ask",
    "manual": "ask",
    "scoped": "scoped",
    "smart": "scoped",
    "smart_auto": "scoped",
    "smart-auto": "scoped",
    "smart auto": "scoped",
    "auto": "auto",
    "automatic": "auto",
    "full": "full",
    "full_access": "full",
    "full-access": "full",
    "full access": "full",
    "full_auto": "auto",
    "full-auto": "auto",
    "full auto": "auto",
}
AUTONOMY_LABELS: dict[str, str] = {
    "ask": "Ask for approval",
    "scoped": "Approve for me",
    "auto": "Automatic",
    "full": "Full access",
}
DEFAULT = "scoped"
CONFIG_DEFAULT = "scoped"
"""The ``automation.autonomy`` value used when the instance config has no
setting. Constitution invariant 11: the default is ``scoped``, not ``auto``.
"auto" is honored only when the owner saved it explicitly."""
UNREADABLE_DEFAULT = "ask"
"""Used when the config cannot be read/parsed or holds an invalid value: an
error never widens autonomy (fail closed → ask)."""


def normalize_autonomy(raw: Any) -> str | None:
    """Map owner-facing mode names (Manual/Smart Auto/Full Auto) onto canonical ids."""
    text = str(raw or "").strip().lower()
    return AUTONOMY_ALIASES.get(text)


def permissions_mode_for(autonomy: str) -> str:
    """Internal ``permissions.mode`` derived from owner-facing autonomy.

    ``auto``/``full`` → ``allow`` (headless auto-approve). ``ask`` and ``scoped``
    → ``confirm``. Specific deny rules are unchanged.
    """
    return "allow" if (autonomy or "").strip().lower() in {"auto", "full"} else "confirm"


def autonomy_from_permissions_mode(mode: str) -> str:
    """Backward-compatible read of a legacy ``permissions.mode`` value."""
    return "auto" if (mode or "").strip().lower() == "allow" else "scoped"


_DESC = {
    "ask": "work in the normal sandbox and ask before actions that need more authority",
    "scoped": "use a reviewer to approve eligible actions while retaining the normal sandbox",
    "auto": "run permitted tools automatically inside the normal sandbox",
    "full": "unrestricted local execution; bypass Jaeger approval and sandbox policy",
}


def auto_approves(mode: str | None) -> bool:
    """Whether routine eligible actions run without an approval card."""
    return str(mode or "").strip().lower() in {"auto", "full"}


def full_access_enabled(mode: str | None) -> bool:
    """Whether the owner explicitly selected unrestricted local execution."""
    return str(mode or "").strip().lower() == "full"

_state: dict[str, Any] = {"mode": DEFAULT, "explicit": False}


def current_autonomy() -> str:
    return _state["mode"]


def configured_autonomy(config_path: Path | str | None) -> str:
    """The instance's saved ``automation.autonomy``.

    - setting absent (or no config file / no path) → ``CONFIG_DEFAULT`` ("scoped")
    - file unreadable or unparsable, or an invalid value → ``UNREADABLE_DEFAULT`` ("ask")
    """
    if not config_path:
        return CONFIG_DEFAULT
    path = Path(config_path)
    try:
        if not path.exists():
            return CONFIG_DEFAULT
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            return UNREADABLE_DEFAULT
        automation = raw.get("automation") or {}
        if not isinstance(automation, dict):
            return UNREADABLE_DEFAULT
        value = automation.get("autonomy")
        if value is None or str(value).strip() == "":
            # A legacy install that only set permissions.mode=allow must
            # keep auto-approve; otherwise the default is scoped.
            permissions = raw.get("permissions") or {}
            mode = permissions.get("mode") if isinstance(permissions, dict) else None
            if str(mode or "").strip().lower() == "allow":
                return "auto"
            return CONFIG_DEFAULT
        norm = normalize_autonomy(value)
        return norm if norm in AUTONOMY else UNREADABLE_DEFAULT
    except Exception:  # noqa: BLE001 — an unreadable config never widens autonomy
        return UNREADABLE_DEFAULT


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
    return {
        "autonomy": m,
        "label": AUTONOMY_LABELS.get(m, m),
        "options": list(AUTONOMY),
        "labels": dict(AUTONOMY_LABELS),
        "description": _DESC.get(m, ""),
    }


def _publish(mode: str) -> None:
    try:
        from jaeger_agent.core.messages import ModeState
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
    target = normalize_autonomy(name)
    if target not in AUTONOMY:
        return {"ok": False, "error": f"unknown autonomy {name!r}; choose from {list(AUTONOMY)}"}
    _state["mode"] = target
    _state["explicit"] = True
    _publish(target)
    return {"ok": True, "mode": target, "label": AUTONOMY_LABELS.get(target, target)}

def sync_permissions_mode(config_path: Path | str | None) -> str:
    """Make ``automation.autonomy`` the source of truth and derive ``permissions.mode``.

    If the saved file had ``permissions.mode: allow`` while autonomy was
    neither ``auto`` nor ``full``, autonomy is migrated to ``auto`` so auto-approve is not
    lost. Specific deny / grant rules are not touched. Returns the
    autonomy value after the sync. No write when already consistent.
    """
    if not config_path:
        return CONFIG_DEFAULT
    path = Path(config_path)
    if not path.is_file():
        return CONFIG_DEFAULT
    try:
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml

        config = load_yaml(path, Config)
        saved = getattr(getattr(config, "automation", None), "autonomy", None)
        mode = getattr(getattr(config, "permissions", None), "mode", None)
        autonomy = str(saved or "").strip().lower()
        if autonomy not in AUTONOMY:
            autonomy = autonomy_from_permissions_mode(str(mode or ""))
        elif autonomy not in {"auto", "full"} and str(mode or "").strip().lower() == "allow":
            # Preserve a previously saved auto-approve posture.
            autonomy = "auto"
        derived = permissions_mode_for(autonomy)
        changed = False
        if getattr(config.automation, "autonomy", None) != autonomy:
            config.automation.autonomy = autonomy
            changed = True
        if getattr(config.permissions, "mode", None) != derived:
            config.permissions.mode = derived
            changed = True
        if changed:
            dump_yaml(path, config)
        return autonomy
    except Exception:  # noqa: BLE001 — never widen on a failed migrate
        return configured_autonomy(path)
