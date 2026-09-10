"""Resolve the local Ollama OpenAI-compat base URL without baking hosts into
remotely served templates.

Order:
  1. ``OLLAMA_BASE_URL`` (full URL, with or without ``/v1``)
  2. ``OLLAMA_HOST`` (``host``, ``host:port``, or URL)
  3. First reachable candidate among loopback and the container→Mac bridge
     address from :mod:`jaeger_ai.core.runtime.host_environment`
  4. Loopback default (Mac-side operator path)

Server-side code calls this helper. Browser/static templates must never
hardcode ``127.0.0.1:11434`` — they should ask the gateway / profile config.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

_DEFAULT_PORT = 11434
_PROBE_TIMEOUT_S = 0.2


def _normalize_openai_base(url: str) -> str:
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "http://" + text
    if text.endswith("/v1"):
        return text
    return text + "/v1"


def _host_port_from_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or _DEFAULT_PORT
    return host, port


def _reachable(host: str, port: int = _DEFAULT_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False


def _container_bridge_host() -> str:
    try:
        from jaeger_ai.core.runtime.host_environment import snapshot
        host = str((snapshot([]).get("container_host_address") or "")).strip()
        return host or "192.168.64.1"
    except Exception:  # noqa: BLE001
        return "192.168.64.1"


def _running_in_container() -> bool:
    if os.environ.get("JAEGER_IN_CONTAINER", "").strip().lower() in {"1", "true", "yes"}:
        return True
    for marker in ("/.dockerenv", "/run/.containerenv"):
        try:
            if Path(marker).exists():
                return True
        except OSError:
            continue
    # Apple container / Lima guests commonly see the Mac at the bridge IP.
    return False


def resolve_ollama_base_url(*, openai_compat: bool = True) -> str:
    """Return the Ollama base URL for Jaeger runtime code (not templates)."""
    env_base = os.environ.get("OLLAMA_BASE_URL", "").strip()
    if env_base:
        return _normalize_openai_base(env_base) if openai_compat else env_base.rstrip("/")

    env_host = os.environ.get("OLLAMA_HOST", "").strip()
    if env_host:
        base = _normalize_openai_base(env_host)
        return base if openai_compat else base.removesuffix("/v1")

    bridge = _container_bridge_host()
    if _running_in_container():
        candidates = [bridge, "127.0.0.1", "localhost"]
        chosen = bridge
    else:
        # Mac / host process: loopback first; bridge is for guests only.
        candidates = ["127.0.0.1", "localhost", bridge]
        chosen = "127.0.0.1"
    for host in candidates:
        if _reachable(host, _DEFAULT_PORT):
            chosen = host
            break
    root = f"http://{chosen}:{_DEFAULT_PORT}"
    return f"{root}/v1" if openai_compat else root


def normalize_ollama_provider(provider: str) -> str:
    """Map product lanes ``ollama-local`` / ``ollama-cloud`` onto the daemon."""
    name = (provider or "").strip().lower()
    if name in {"ollama-local", "ollama-cloud", "ollama_cloud", "ollamacloud"}:
        return "ollama"
    return name


__all__ = [
    "normalize_ollama_provider",
    "resolve_ollama_base_url",
]
