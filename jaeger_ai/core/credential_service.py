"""Validated, non-leaking access to an instance's credential store.

External surfaces may list names and mutate values through this service. Raw
credential values are deliberately never returned across the bridge.
"""

from __future__ import annotations

from typing import Any


def list_credentials(layout: Any) -> dict[str, Any]:
    from jaeger_agent import credentials

    names = sorted(str(name) for name in credentials.list_credentials(layout))
    return {"credentials": names, "count": len(names)}


def set_credential(layout: Any, name: Any, value: Any) -> dict[str, Any]:
    from jaeger_agent import credentials

    credential_name = str(name or "").strip()
    credential_value = str(value or "").strip()
    if not credential_name:
        raise ValueError("credential name is required")
    if not credential_value:
        raise ValueError("credential value is required")
    credentials.set_credential(layout, credential_name, credential_value)
    return {"ok": True, "name": credential_name, "stored": True}


def delete_credential(layout: Any, name: Any) -> dict[str, Any]:
    from jaeger_agent import credentials

    credential_name = str(name or "").strip()
    if not credential_name:
        raise ValueError("credential name is required")
    removed = bool(credentials.delete_credential(layout, credential_name))
    return {"ok": True, "name": credential_name, "removed": removed}


__all__ = ["delete_credential", "list_credentials", "set_credential"]
