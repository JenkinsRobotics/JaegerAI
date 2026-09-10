"""Identity-scoped, audited capability grants for host operations.

Enforces workspace root sandboxing, authorization tiers, and audit logging.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_ai.core.ares_interop import ares_home

MAX_BYTES = 1_000_000
IDENTITY = os.environ.get("ARES_CAPABILITY_IDENTITY", "jaeger").strip()
GRANTS_PATH = Path(
    os.environ.get("ARES_CAPABILITY_GRANTS")
    or ares_home() / "capabilities" / "grants.json"
)
AUDIT_PATH = Path(
    os.environ.get("ARES_CAPABILITY_AUDIT")
    or ares_home() / "audit" / "host-capabilities.jsonl"
)


def get_current_identity() -> str:
    return os.environ.get("ARES_CAPABILITY_IDENTITY", "jaeger").strip() or "jaeger"


def _grant() -> dict[str, Any]:
    identity = get_current_identity()
    if identity not in {"admin", "hermes", "jaeger", "openclaw"}:
        raise PermissionError(f"Host capability identity is missing or invalid: {identity}")
    if not GRANTS_PATH.exists():
        # Fallback minimal grant if file missing
        return {
            "roots": [str(Path.home() / "workspace"), str(Path.home() / "GitHub")],
            "capabilities": ["capabilities.inspect", "workspace.read", "workspace.list", "service.status"],
        }
    raw = json.loads(GRANTS_PATH.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise RuntimeError("Unsupported host-capability grant version")
    grant = (raw.get("identities") or {}).get(identity)
    if not isinstance(grant, dict):
        raise PermissionError(f"No host capability grant exists for {identity}")
    return grant


def _roots(grant: dict[str, Any] | None = None) -> list[Path]:
    value = grant or _grant()
    roots = [Path(str(item)).expanduser().resolve() for item in value.get("roots") or []]
    if not roots:
        roots = [Path.home() / "workspace"]
    return roots


def _require(capability: str) -> dict[str, Any]:
    grant = _grant()
    identity = get_current_identity()
    capabilities = set(grant.get("capabilities") or [])
    # Admin has all capabilities; others must match explicit grant
    if identity != "admin" and capability not in capabilities:
        raise PermissionError(f"{identity} is not granted capability: {capability}")
    return grant


def _resolve(path: str, *, must_exist: bool = True, capability: str = "") -> Path:
    grant = _grant()
    roots = _roots(grant)
    requested = str(path or "").strip()
    if not requested or requested == "/workspace":
        candidate = roots[0]
    elif requested.startswith("/workspace/"):
        candidate = roots[0] / requested.removeprefix("/workspace/")
    else:
        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = roots[0] / candidate
    try:
        resolved = candidate.resolve(strict=must_exist)
        if not must_exist and not candidate.exists():
            resolved = candidate.parent.resolve(strict=True) / candidate.name
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise PermissionError(f"Path is outside approved workspace roots: {requested}")
        return resolved
    except Exception as exc:
        if capability:
            _audit(
                capability, outcome="denied", requested_path=requested[:1024],
                error=type(exc).__name__,
            )
        raise


def _audit(capability: str, *, outcome: str, path: Path | None = None, **details: Any) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    AUDIT_PATH.parent.chmod(0o700)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "identity": get_current_identity(),
        "capability": capability,
        "outcome": outcome,
        "path": str(path) if path else None,
        "details": details,
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
