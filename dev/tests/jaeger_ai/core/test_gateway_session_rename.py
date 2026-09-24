"""The Gateway owns session titles; clients rename through PATCH /v1/sessions/{id}."""
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def test_store_rename_keeps_updated_at_so_the_sidebar_does_not_reorder(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    before = store.ensure_session("a", title="New Conversation")
    renamed = store.rename_session("a", "Plan the release")
    assert renamed["title"] == "Plan the release"
    assert renamed["updated_at"] == before["updated_at"]


def test_store_rename_unknown_session_is_none(tmp_path: Path):
    assert GatewaySessionStore(tmp_path / "s.sqlite3").rename_session("missing", "x") is None


class TestRenameRoute(AioHTTPTestCase):
    async def get_application(self):
        import tempfile
        self.db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        self.gateway_app = JaegerGatewayApp(store=GatewaySessionStore(self.db_path))
        return self.gateway_app.app

    async def tearDownAsync(self):
        await super().tearDownAsync()
        if self.db_path.exists():
            self.db_path.unlink()

    async def test_rename_updates_lists_and_announces(self):
        # The Gateway mints and owns session IDs; a client adopts the id the
        # create response returns (a client-supplied id is never trusted).
        created = await (await self.client.request(
            "POST", "/v1/sessions", json={"session_id": "s1"},
        )).json()
        sid = created["session_id"]
        resp = await self.client.request("PATCH", f"/v1/sessions/{sid}", json={"title": "  Fix the loop  "})
        assert resp.status == 200
        assert (await resp.json())["title"] == "Fix the loop"
        listed = (await (await self.client.request("GET", "/v1/sessions")).json())["sessions"]
        assert listed[0]["title"] == "Fix the loop"
        events = [e.event for e in self.gateway_app.event_bus.get_replay_events(sid)]
        assert "session.updated" in events

    async def test_rejects_bad_bodies_and_unknown_sessions(self):
        created = await (await self.client.request(
            "POST", "/v1/sessions", json={"session_id": "s1"},
        )).json()
        sid = created["session_id"]
        for body in ({}, {"title": ""}, {"title": "   "}, {"title": 5}, []):
            resp = await self.client.request("PATCH", f"/v1/sessions/{sid}", json=body)
            assert resp.status == 400, body
        resp = await self.client.request("PATCH", "/v1/sessions/nope", json={"title": "x"})
        assert resp.status == 404


class TestSkillsRoute(AioHTTPTestCase):
    async def get_application(self):
        import tempfile
        self.db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        return JaegerGatewayApp(store=GatewaySessionStore(self.db_path)).app

    async def tearDownAsync(self):
        await super().tearDownAsync()
        if self.db_path.exists():
            self.db_path.unlink()

    async def test_lists_skills_without_bodies_or_paths(self):
        resp = await self.client.request("GET", "/v1/runtime/skills")
        data = await resp.json()
        assert resp.status == 200 and data["count"] == len(data["skills"]) > 100
        assert {"name", "category", "description", "lifecycle"} == set(data["skills"][0])
        # The imported Codex skills are offered like any other.
        assert any(s["category"] == "codex" for s in data["skills"])

    async def test_filters_by_name_or_description(self):
        resp = await self.client.request("GET", "/v1/runtime/skills?q=contract")
        names = [s["name"] for s in (await resp.json())["skills"]]
        assert "contract-review" in names or any("contract" in n for n in names)
        assert all("contract" in (s["name"] + s["description"]).lower()
                   for s in (await (await self.client.request("GET", "/v1/runtime/skills?q=contract")).json())["skills"])
