"""GB-031/GB-032 routes are mounted on the real Gateway app and stay owner-admin only."""
import tempfile
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

ROUTES = [
    ("POST", "/v1/authority/preview", {"tool_name": "read_file"}),
    ("GET", "/v1/authority/review-rules", None),
    ("GET", "/v1/connector-grants", None),
    ("POST", "/v1/connector-grants", {"connector": "x", "account_id": "a", "tools": ["t"]}),
    ("GET", "/v1/connector-grants/nope", None),
    ("POST", "/v1/connector-grants/nope/revoke", {}),
    ("POST", "/v1/connector-grants/nope/check", {"tool": "t"}),
]


class TestBlueprintRoutesMounted(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.gateway_app = JaegerGatewayApp(store=GatewaySessionStore(self.tmp / "s.sqlite3"))
        return self.gateway_app.app

    async def _req(self, caller, method, path, body):
        kw = {"headers": client_headers(caller)}
        if body is not None:
            kw["json"] = body
        return await self.client.request(method, path, **kw)

    async def test_owner_admin_reaches_every_route(self):
        for method, path, body in ROUTES:
            resp = await self._req("cli", method, path, body)
            assert resp.status not in (401, 403, 405), (method, path, resp.status)
            assert resp.status != 404 or path.endswith("/nope") or "/nope/" in path, (method, path)
        resp = await self._req("cli", "GET", "/v1/connector-grants", None)
        assert resp.status == 200 and "grants" in await resp.json()

    async def test_non_admin_caller_is_refused(self):
        for method, path, body in ROUTES:
            resp = await self._req("bridge", method, path, body)  # owner caller without admin scope
            assert resp.status == 403, (method, path, resp.status)
