"""Optional ARES application bridge used by Jaeger AI settings surfaces."""

from __future__ import annotations

import os
import subprocess
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any


def base_url() -> str:
    return (os.environ.get("JAEGER_ARES_URL") or "http://127.0.0.1:8788").rstrip("/")


def health(*, timeout: float = 1.0) -> dict[str, Any]:
    """Probe the optional local ARES controller without starting it."""
    url = f"{base_url()}/health"
    try:
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"online": response.status == 200, "status": response.status, "url": url}
    except Exception as exc:  # noqa: BLE001 — offline is a normal optional state
        return {"online": False, "status": None, "url": url, "error": str(exc)}


def open_web() -> bool:
    return bool(webbrowser.open(base_url()))


def open_app() -> dict[str, Any]:
    """Open ARES.app using portable user/system locations or LaunchServices."""
    candidates = (Path.home() / "Applications" / "ARES.app", Path("/Applications/ARES.app"))
    try:
        app = next((path for path in candidates if path.exists()), None)
        command = ["open", str(app)] if app is not None else ["open", "-a", "ARES"]
        subprocess.Popen(command)
        return {"opened": True, "path": str(app) if app is not None else "ARES"}
    except OSError as exc:
        return {"opened": False, "error": str(exc)}


__all__ = ["base_url", "health", "open_app", "open_web"]
