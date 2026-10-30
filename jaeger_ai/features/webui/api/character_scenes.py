"""Authenticated same-origin read-through for character scenes and pack media."""
from __future__ import annotations

import http.client
import re
from urllib.parse import urlparse


def route(handler, parsed) -> bool:
    if not re.fullmatch(r"/v1/characters/[^/]+/scene(?:/assets/[\w-]{1,80})?", parsed.path):
        return False
    from api.jaeger_agents import gateway_base
    from api.helpers import bad
    from jaeger_ai.core.gateway.caller_auth import client_headers
    target = urlparse(gateway_base())
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=8)
    try:
        headers = {"Accept": "*/*", **client_headers("webui")}
        # Preserve byte ranges for native video seeking/metadata playback.
        if value := handler.headers.get("Range"):
            headers["Range"] = value
        connection.request("GET", parsed.path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        handler.send_response(response.status)
        for name in ("Content-Type", "Content-Range", "Accept-Ranges"):
            if value := response.getheader(name):
                handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "private, no-cache")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(body)
        return True
    except (OSError, http.client.HTTPException):
        bad(handler, "Character scene is unavailable", 503)
        return True
    finally:
        connection.close()
