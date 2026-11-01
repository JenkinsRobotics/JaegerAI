"""Gateway routes for the shared UI layout preset (loopback only).

GET  /v1/ui/layout -> {preset, updated_at}
POST /v1/ui/layout -> {preset}  (owner surfaces only; one of PRESETS)

One record so the Mac app, the browser and the iPhone PWA show the same look.
Stored at $JAEGER_STATE_HOME/ui/layout.json.
"""
from __future__ import annotations

import ipaddress
import json
import os
import time
from pathlib import Path

from aiohttp import web

PRESETS = ("glass", "arc", "linear", "dia")
DEFAULT = "glass"


def state_path() -> Path:
    home = os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_HOME") or str(Path.home() / ".jaeger")
    return Path(home).expanduser() / "ui" / "layout.json"


def load(path: Path | None = None) -> dict:
    path = path or state_path()
    try:
        data = json.loads(path.read_text())
        if data.get("preset") in PRESETS:
            return {"preset": data["preset"], "updated_at": float(data.get("updated_at") or 0)}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {"preset": DEFAULT, "updated_at": 0.0}


def save(preset: str, path: Path | None = None) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"preset": preset, "updated_at": time.time()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)
    return record


def _owner(name: str) -> bool:
    from jaeger_ai.core.gateway.caller_auth import CALLERS
    spec = CALLERS.get(name)
    return bool(spec and str(getattr(spec, "actor", "")).startswith("owner:"))


def register(gateway, path: Path | None = None):
    def loopback(request) -> None:
        if not request.remote or not ipaddress.ip_address(request.remote).is_loopback:
            raise web.HTTPForbidden(text="Loopback required")

    async def get_layout(request):
        loopback(request)
        return web.json_response({**load(path), "presets": list(PRESETS)})

    async def set_layout(request):
        loopback(request)
        caller = request.get("caller")
        if caller is not None and not _owner(caller.name):
            return web.json_response({"error": "owner surfaces only"}, status=403)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or set(body) - {"preset"}:
            return web.json_response({"error": "expected {preset}"}, status=400)
        try:
            record = save(str(body.get("preset", "")), path)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            gateway.event_bus.publish("*", "ui.layout", {"preset": record["preset"]})
        except Exception:  # noqa: BLE001
            pass
        return web.json_response(record)

    gateway.app.router.add_get("/v1/ui/layout", get_layout)
    gateway.app.router.add_post("/v1/ui/layout", set_layout)
