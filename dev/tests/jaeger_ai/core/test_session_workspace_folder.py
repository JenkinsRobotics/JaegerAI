"""POST /v1/sessions workspace_folder -> the session's workspace (project_root for
tools, ide_context fallback); ide_context accepts the jaeger-tab shape."""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.entity.ide_context import clean
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest_asyncio.fixture
async def gw(tmp_path):
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.sqlite3"))
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as c:
        yield gateway, c


@pytest.mark.asyncio
async def test_workspace_folder_validated_and_used(gw, tmp_path):
    gateway, client = gw
    ws = tmp_path / "proj"
    ws.mkdir()
    r = await client.post("/v1/sessions", json={"session_id": "w1", "workspace_folder": str(ws)})
    assert r.status in (200, 201), await r.text()
    body = await r.json()
    real = os.path.realpath(ws)
    assert body["workspace"] == real and body["metadata"]["workspace_folder"] == real
    admitted = gateway.store.admit_request("w1", "hi", request_id="r1")
    assert admitted["execution"]["workspace"] == real  # the turn's project_root
    for bad in ("relative/dir", str(tmp_path / "missing"), "/", os.path.expanduser("~"), "", str(ws / "f.txt")):
        if bad.endswith("f.txt"):
            (ws / "f.txt").write_text("x")
        resp = await client.post("/v1/sessions", json={"session_id": "w-bad", "workspace_folder": bad})
        assert resp.status == 400, bad
        assert (await resp.json())["field"] == "workspace_folder"
    plain = await client.post("/v1/sessions", json={"session_id": "w2"})
    assert (await plain.json())["workspace"] == ""  # omitted: unchanged behaviour


@pytest.mark.asyncio
async def test_ide_context_falls_back_to_session_folder(gw, tmp_path):
    gateway, client = gw
    ws = tmp_path / "proj2"
    ws.mkdir()
    await client.post("/v1/sessions", json={"session_id": "w3", "workspace_folder": str(ws)})
    out = gateway._ide_request("w3", "r", "context", {}, 0.1)  # no IDE loop in this test
    assert out["ok"] and out["fallback"] and out["result"]["workspace_folder"] == os.path.realpath(ws)
    assert gateway._ide_request("w3", "r", "open_file", {}, 0.1)["ok"] is False  # only context falls back
    merged = gateway._ide_context_fallback("w3", "context", {"ok": True, "result": {"active_file": {"path": "/a.py"}}})
    assert merged["result"] == {"active_file": "/a.py", "workspace_folder": os.path.realpath(ws)}


def test_clean_accepts_jaeger_tab_shape():
    raw = {"workspace_folder": "/p", "workspace_folders": ["/p", "/q"], "unknown": 1,
           "active_file": {"path": "/p/a.ts", "language": "typescript"},
           "selection": {"text": "x = 1", "start": {"line": 0, "char": 2}, "end": {"line": 4, "char": 0}}}
    out = clean(raw)
    assert out["workspace_folder"] == "/p" and out["workspace_folders"] == ["/p", "/q"]
    assert out["active_file"] == "/p/a.ts" and out["language"] == "typescript" and "unknown" not in out
    assert out["selection"]["start_line"] == 1 and out["selection"]["end_line"] == 5
    assert out["selection"]["start"] == {"line": 0, "char": 2} and clean(out) == out  # idempotent
    legacy = clean({"active_file": "/x.py", "language": "python", "selection": {"text": "y", "start_line": 3, "end_line": 4}})
    assert legacy["active_file"] == "/x.py" and legacy["selection"]["start_line"] == 3
