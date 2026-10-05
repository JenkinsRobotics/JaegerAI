"""WebUI listen address. Loopback unless the owner explicitly re-opens LAN."""
from __future__ import annotations

import os
from typing import Mapping


def webui_bind_host(environ: Mapping[str, str] | None = None) -> str:
    """``JAEGER_WEBUI_HOST=0.0.0.0`` alone does not publish the WebUI.

    Tailscale Serve proxies the loopback port. That is the remote path.
    """
    env = os.environ if environ is None else environ
    allow = str(env.get("JAEGER_WEBUI_ALLOW_LAN", "")).strip().lower()
    if allow in {"1", "true", "yes", "on"}:
        return str(env.get("JAEGER_WEBUI_HOST") or "0.0.0.0")
    return "127.0.0.1"
