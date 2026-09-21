"""Durable remote-access policy for one operator Jaeger.

State lives under the operator/instance state root, never in the git tree.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any


def state_path() -> Path:
    from jaeger_ai.core.instance.instance import operator_state_root

    root = operator_state_root()
    inst = os.environ.get("JAEGER_INSTANCE_DIR", "").strip()
    if inst:
        return Path(inst).expanduser() / "run" / "remote_access.json"
    return root / "remote_access.json"


def load() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return {"enabled": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False}
    return data if isinstance(data, dict) else {"enabled": False}


def save(data: dict[str, Any]) -> Path:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updated_at"] = int(time.time())
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".remote.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def ensure_token(data: dict[str, Any] | None = None) -> str:
    state = dict(data or load())
    token = str(state.get("token") or "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        state["token"] = token
        save(state)
    return token
