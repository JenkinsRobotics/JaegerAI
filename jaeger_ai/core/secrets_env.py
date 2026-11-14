"""Load owner-only secrets from ``~/.jaeger/secrets.env`` into the process env.

Jaeger reads ``OLLAMA_API_KEY`` (and any other keys in that file) only from
this store. The file must be owner-read/write (0600). Values are never
logged or printed. A missing or empty file is fine: callers treat the key
as absent and surface a "needs API key" status instead of failing boot.
"""

from __future__ import annotations

import os
from pathlib import Path

SECRETS_ENV_NAME = "secrets.env"
_LOADED = False

# Conventional aliases accepted *inside* secrets.env only. After load they
# appear as normal process environment variables for existing resolvers.
_OLLAMA_KEY_NAMES = ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY")


def secrets_env_path() -> Path:
    root = (os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_STATE_HOME") or "").strip()
    if root:
        return Path(root).expanduser() / SECRETS_ENV_NAME
    return Path.home() / ".jaeger" / SECRETS_ENV_NAME


def load_secrets_env(*, override: bool = False) -> Path | None:
    """Load ``KEY=VALUE`` pairs from the secrets file into ``os.environ``.

    Refuses to load a world- or group-readable file. Does not override a
    non-empty variable already present in the process environment unless
    ``override`` is true. Never logs values.
    """
    global _LOADED
    path = secrets_env_path()
    if not path.is_file():
        _LOADED = True
        return None
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            _LOADED = True
            return path
        text = path.read_text(encoding="utf-8")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            existing = os.environ.get(key, "").strip()
            if override or not existing:
                os.environ[key] = value
    except OSError:
        pass
    _LOADED = True
    return path


def ollama_api_key() -> str:
    """Return the Ollama Cloud API key from the Jaeger secrets file / env."""
    if not _LOADED:
        load_secrets_env()
    for name in _OLLAMA_KEY_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


# Load once at import so ``python -m jaeger_ai...`` launch agents pick it up.
load_secrets_env()
