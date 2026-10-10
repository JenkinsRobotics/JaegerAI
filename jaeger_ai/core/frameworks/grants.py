"""Owner grants for reading other frameworks' data, one per framework + capability.

Only the owner sets these (the Gateway route needs the ``admin`` scope, which
jaegerd's own caller does not have), so the agent cannot grant itself access.
Every change and every read is appended to an audit log (no content).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

CAPABILITIES = ("read_sessions", "read_memory", "delegate")
_LOCK = threading.Lock()


def default_path() -> Path:
    home = Path(os.environ.get("JAEGER_HOME", str(Path.home() / ".jaeger")))
    return home / "instances" / "jaeger" / "framework_grants.json"


class FrameworkGrants:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or default_path())
        self.audit_path = self.path.with_name("framework_audit.jsonl")

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def all(self) -> dict[str, dict[str, Any]]:
        return self._load().get("grants", {})

    def is_granted(self, fid: str, capability: str) -> bool:
        return bool(((self.all().get(fid) or {}).get(capability) or {}).get("granted"))

    def set(self, fid: str, capability: str, granted: bool, *, by: str) -> dict[str, Any]:
        if capability not in CAPABILITIES:
            raise ValueError(f"unknown capability {capability!r}")
        with _LOCK:
            data = self._load()
            grants = data.setdefault("grants", {})
            grants.setdefault(fid, {})[capability] = {"granted": bool(granted), "by": by, "at": time.time()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            tmp.replace(self.path)
        self.audit("grant" if granted else "revoke", fid, capability=capability, by=by)
        return grants[fid]

    def audit(self, event: str, fid: str, **fields: Any) -> None:
        rec = {"at": time.time(), "event": event, "framework": fid, **fields}
        try:
            with _LOCK, self.audit_path.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass
