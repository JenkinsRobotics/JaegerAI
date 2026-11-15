"""Relay configuration and state under ``~/.jaeger/channels`` (owner-only files)."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

#: Secret name (in ``~/.jaeger/secrets.env``) for Jaeger's own Telegram bot.
TELEGRAM_TOKEN_ENV = "JAEGER_TELEGRAM_BOT_TOKEN"

DEFAULTS: dict[str, Any] = {
    "home_agent": "native:jaeger",
    "telegram": {
        "enabled": True,
        # Exactly one private chat (Matthew's). Empty until paired.
        "allowed_chat_id": None,
        "pairing_code": None,
        "pairing_expires_at": None,
    },
    "imessage": {
        "enabled": True,
        # The owner's own handles. Only the 1:1 self-chat on these handles is
        # read, and replies only ever go to ``send_to`` (one of these).
        "self_handles": [],
        "send_to": None,
        "service": "iMessage",
    },
    "deliver": {
        # Which channels receive outbound deliveries (in order of preference).
        "channels": ["telegram", "imessage"],
        # "first": only the first live channel; "all": every live channel.
        "fanout": "first",
        "schedules": True,
        "approvals": True,
        "notifications": True,
    },
    # Prefix on every relay-sent message; also used for echo suppression in the
    # iMessage self-chat (the owner's own messages never start with it).
    "reply_prefix": "Jaeger: ",
}


def state_dir() -> Path:
    root = os.environ.get("JAEGER_STATE_DIR") or str(Path.home() / ".jaeger")
    path = Path(root).expanduser() / "channels"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _config_path() -> Path:
    return state_dir() / "config.json"


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            out[key] = _merge(base[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict[str, Any]:
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    return _merge(DEFAULTS, data if isinstance(data, dict) else {})


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_config(cfg: dict[str, Any]) -> None:
    write_json(_config_path(), cfg)


def read_state(name: str) -> dict[str, Any]:
    path = state_dir() / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(name: str, data: dict[str, Any]) -> None:
    write_json(state_dir() / f"{name}.json", data)


def new_pairing_code(cfg: dict[str, Any], ttl_s: int = 3600) -> str:
    """Issue a one-hour Telegram pairing code (6 digits)."""
    code = f"{secrets.randbelow(10**6):06d}"
    cfg.setdefault("telegram", {})
    cfg["telegram"]["pairing_code"] = code
    cfg["telegram"]["pairing_expires_at"] = time.time() + ttl_s
    save_config(cfg)
    return code


def telegram_token() -> str | None:
    """Jaeger's bot token from the env or ``~/.jaeger/secrets.env``. Never logged."""
    value = os.environ.get(TELEGRAM_TOKEN_ENV, "").strip()
    if value:
        return value
    try:
        from jaeger_ai.core.secrets_env import secrets_env_path
        path = secrets_env_path()
    except Exception:  # noqa: BLE001
        path = Path.home() / ".jaeger" / "secrets.env"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if line.startswith(TELEGRAM_TOKEN_ENV + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None
