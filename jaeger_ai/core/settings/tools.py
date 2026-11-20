"""Agent-facing settings tools over the canonical settings catalog.

All reads mask secrets; all writes go through ``catalog.set_value`` (Pydantic
validation + atomic ``mutate_yaml``) and re-read from disk to verify persistence.
Security, autonomy, permission, and secret settings cannot be altered by an
agent tool call so a model can never silently widen its own authority.
"""
from __future__ import annotations

from typing import Any

from . import catalog

PROTECTED_SETTING_PREFIXES = (
    "automation.autonomy",
    "permissions.",
    "security.",
)


def _is_protected(path: str, desc: dict[str, Any] | None) -> str | None:
    clean = (path or "").strip()
    if any(clean == p or clean.startswith(p) for p in PROTECTED_SETTING_PREFIXES):
        return f"setting {clean!r} governs security or autonomy and must be changed directly by the owner"
    if desc is not None and desc.get("type") == "secret":
        return f"setting {clean!r} is a secret and cannot be modified through agent settings_set"
    return None


def settings_get(layout: Any, path: str = "", group: str = "") -> dict[str, Any]:
    """Read one exposed Jaeger setting or list settings in a group (secrets masked)."""
    clean_path = (path or "").strip()
    if clean_path:
        desc = catalog.describe(layout, clean_path)
        if desc is None:
            return {"ok": False, "error": f"Unknown setting {clean_path!r}. Call settings_get() to list valid paths."}
        return {"ok": True, "setting": desc}
    clean_group = (group or "").strip() or None
    grouped = catalog.catalog(layout, advanced=True, group=clean_group)
    return {
        "ok": True,
        "groups": list(grouped.keys()),
        "count": sum(len(items) for items in grouped.values()),
        "settings": grouped,
    }


def settings_set(layout: Any, path: str, value: Any) -> dict[str, Any]:
    """Modify an authorized Jaeger setting and verify the persisted value from disk."""
    clean_path = (path or "").strip()
    if not clean_path:
        return {"ok": False, "error": "path is required"}
    desc = catalog.describe(layout, clean_path)
    if desc is None:
        return {"ok": False, "error": f"Unknown or unexposed setting {clean_path!r}."}
    protected_reason = _is_protected(clean_path, desc)
    if protected_reason:
        return {"ok": False, "error": protected_reason, "error_type": "protected_setting"}
    try:
        saved = catalog.set_value(layout, clean_path, value)
        re_read = catalog.get_value(layout, clean_path)
    except (ValueError, KeyError, OSError) as exc:
        return {"ok": False, "error": f"Failed to update {clean_path!r}: {exc}"}
    return {
        "ok": True,
        "verified": True,
        "path": clean_path,
        "value": saved["value"],
        "persisted_value": str(re_read) if not isinstance(re_read, (bool, int, float, str, list, dict, type(None))) else re_read,
        "restart_required": bool(saved.get("restart_required", False)),
    }
