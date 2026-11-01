"""Gateway routes for the shared Jaeger logo choice (loopback only, J-085).

GET  /v1/ui/logo -> {logo, custom?: {mime, data_url}, updated_at, builtins}
POST /v1/ui/logo -> {logo} | {logo: "custom", custom: {mime, data_base64}}  (owner surfaces only)

Sits next to layout.json as $JAEGER_STATE_HOME/ui/logo.json so the Mac app, the browser and the
iPhone PWA show the same mark. A custom SVG is sanitized here (allow-listed shape elements and
attributes only: no script, event handlers, foreignObject, external references or DTDs).
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from aiohttp import web

BUILTINS = ("shield-j", "shield-j-tile", "shield", "j", "wordmark", "classic")
DEFAULT = "shield-j"
MAX_BYTES = 200_000
RASTER = {"image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF", "image/jpeg": b"\xff\xd8\xff"}
SVG_NS = "http://www.w3.org/2000/svg"
XLINK = "{http://www.w3.org/1999/xlink}href"
ELEMENTS = {"svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "defs", "lineargradient",
            "radialgradient", "stop", "title", "desc", "clippath", "mask", "use", "text", "tspan", "symbol"}
ATTR_OK = re.compile(r"^(?:[a-z][a-z0-9:-]*)$")
URL_REF = re.compile(r"url\(\s*(?!['\"]?#)", re.I)


def state_path() -> Path:
    home = os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_HOME") or str(Path.home() / ".jaeger")
    return Path(home).expanduser() / "ui" / "logo.json"


def sanitize_svg(raw: bytes) -> bytes:
    """Returns a cleaned SVG or raises ValueError. Unknown elements are dropped with their children."""
    text = raw.decode("utf-8", errors="strict")
    if re.search(r"<!(?:DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("SVG with a DOCTYPE/ENTITY is not allowed")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"not a readable SVG ({exc})") from None
    if root.tag not in (f"{{{SVG_NS}}}svg", "svg"):
        raise ValueError("the file's root element is not <svg>")

    def clean(el: ET.Element) -> None:
        for child in list(el):
            local = child.tag.split("}")[-1].lower() if isinstance(child.tag, str) else ""
            if local not in ELEMENTS:
                el.remove(child)
                continue
            clean(child)
        for k in list(el.attrib):
            v = el.attrib[k]
            local = k.split("}")[-1].lower()
            bad = (local.startswith("on") or not ATTR_OK.match(local)
                   or ((local == "href" or k == XLINK) and not v.startswith("#"))
                   or URL_REF.search(v) or re.search(r"javascript:|expression\(|@import", v, re.I))
            if bad:
                del el.attrib[k]

    clean(root)
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.tostring(root, encoding="utf-8")


def check_custom(mime: str, data: bytes) -> bytes:
    if not data or len(data) > MAX_BYTES:
        raise ValueError(f"the logo file must be under {MAX_BYTES // 1000} KB")
    if mime == "image/svg+xml":
        return sanitize_svg(data)
    magic = RASTER.get(mime)
    if not magic or not data.startswith(magic):
        raise ValueError("use an SVG, PNG, WebP or JPEG file")
    return data


def load(path: Path | None = None) -> dict:
    path = path or state_path()
    try:
        data = json.loads(path.read_text())
        logo = data.get("logo")
        if logo in BUILTINS:
            return {"logo": logo, "updated_at": float(data.get("updated_at") or 0)}
        c = data.get("custom") or {}
        if logo == "custom" and isinstance(c.get("mime"), str) and isinstance(c.get("data_url"), str):
            return {"logo": "custom", "custom": {"mime": c["mime"], "data_url": c["data_url"]}, "updated_at": float(data.get("updated_at") or 0)}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {"logo": DEFAULT, "updated_at": 0.0}


def save(logo: str, custom: dict | None = None, path: Path | None = None) -> dict:
    path = path or state_path()
    record: dict = {"logo": logo, "updated_at": time.time()}
    if logo == "custom":
        if not isinstance(custom, dict) or not isinstance(custom.get("mime"), str) or not isinstance(custom.get("data_base64"), str):
            raise ValueError("expected custom {mime, data_base64}")
        try:
            raw = base64.b64decode(custom["data_base64"], validate=True)
        except ValueError:
            raise ValueError("custom data is not base64") from None
        clean = check_custom(custom["mime"], raw)
        record["custom"] = {"mime": custom["mime"], "data_url": f"data:{custom['mime']};base64,{base64.b64encode(clean).decode()}"}
    elif logo not in BUILTINS:
        raise ValueError(f"unknown logo {logo!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return record


def register(gateway, path: Path | None = None):
    from .routes import _owner

    def loopback(request) -> None:
        if not request.remote or not ipaddress.ip_address(request.remote).is_loopback:
            raise web.HTTPForbidden(text="Loopback required")

    async def get_logo(request):
        loopback(request)
        return web.json_response({**load(path), "builtins": list(BUILTINS)})

    async def set_logo(request):
        loopback(request)
        caller = request.get("caller")
        if caller is not None and not _owner(caller.name):
            return web.json_response({"error": "owner surfaces only"}, status=403)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or set(body) - {"logo", "custom"}:
            return web.json_response({"error": "expected {logo, custom?}"}, status=400)
        try:
            record = save(str(body.get("logo", "")), body.get("custom"), path)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            gateway.event_bus.publish("*", "ui.logo", {"logo": record["logo"]})
        except Exception:  # noqa: BLE001
            pass
        return web.json_response(record)

    gateway.app.router.add_get("/v1/ui/logo", get_logo)
    gateway.app.router.add_post("/v1/ui/logo", set_logo)
