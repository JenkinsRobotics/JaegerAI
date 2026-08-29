from __future__ import annotations

import json
import threading
from urllib.request import urlopen

from jaeger_ai.cli.entry import _route
from jaeger_ai.interfaces.web.server import JaegerWebServer


class _Bridge:
    instance = "test"

    def health(self):
        return {"ok": True, "instance": "test"}

    def query(self, what, args=None):
        return {"identity": {"display_name": "Test"}, "list_sessions": []}.get(what, {})


def test_cli_routes_web_surface():
    assert _route(["web", "--port", "9999"], "/python") == [
        "/python", "-m", "jaeger_ai.interfaces.web", "--port", "9999"
    ]


def test_health_endpoint_uses_bridge_contract():
    server = JaegerWebServer(("127.0.0.1", 0), "test")
    server.bridge = _Bridge()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/health") as response:
            assert json.load(response) == {"ok": True, "instance": "test"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
