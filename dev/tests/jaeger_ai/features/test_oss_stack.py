"""OSS stack phase 1: model router, shared MCP tools, Documents RAG (2026-10-31)."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from jaeger_ai.core.gateway import agent_activity, caller_auth
from jaeger_ai.features.oss_stack import docs, docs_indexer, router
from jaeger_ai.features.oss_stack.mcp_pool import McpPool, ServerSpec, ToolError, default_specs


def _health(pc=("qwen3:8b",), mac=("qwen3:4b", "gemma4:12b", "qwen3-vl:8b", "qwen3-embedding:0.6b")):
    def fetch(url, timeout):
        if router.PC_URL in url:
            if pc is None:
                raise OSError("down")
            return {"models": [{"name": n} for n in pc] + [{"name": "glm-5.3:cloud", "remote_host": "x"}]}
        return {"models": [{"name": n} for n in mac]}
    return router.Health(fetch=fetch)


def test_cloud_models_refused_and_detected():
    assert router.is_cloud("glm-5.3:cloud") and router.is_cloud("qwen3.5:397b-cloud")
    assert not router.is_cloud("qwen3:8b")
    with pytest.raises(router.RouteError):
        router.decide({"model": "kimi-k2.7-code:cloud"}, _health())
    assert "glm-5.3:cloud" not in _health().models(router.PC_URL)


def test_small_text_goes_to_rackpc():
    d = router.decide({"prompt": "hi"}, _health(), mac_gate=lambda k, m: ["busy"])
    assert d["target"] == "rackpc" and d["model"] == "qwen3:8b"  # PC ignores Mac busy gate


def test_pc_down_falls_back_to_mac_small():
    d = router.decide({"prompt": "hi"}, _health(pc=None), mac_gate=lambda k, m: [])
    assert d["target"] == "mac" and d["model"] == "qwen3:4b" and "fallback" in d["reason"]


@pytest.mark.parametrize("req,model", [({"images": ["x"]}, "qwen3-vl:8b"), ({"kind": "embed"}, "qwen3-embedding:0.6b"),
                                       ({"model": "gemma4:12b"}, "gemma4:12b"), ({"large": True}, "gemma4:12b")])
def test_vision_embed_large_stay_on_mac(req, model):
    d = router.decide(req, _health(), mac_gate=lambda k, m: [])
    assert d["target"] == "mac" and d["model"] == model


def test_mac_busy_gate_respected():
    seen = []
    with pytest.raises(router.RouteError) as e:
        router.decide({"model": "gemma4:12b"}, _health(), mac_gate=lambda k, m: seen.append((k, m)) or ["low memory"])
    assert e.value.status == 503 and e.value.extra["busy"] == ["low memory"] and seen == [("heavy", "gemma4:12b")]


def test_unload_others_keeps_one_large_model():
    posts = []
    out = router.unload_others("gemma4:12b", fetch=lambda u, t: {"models": [{"name": "qwen3-vl:8b"}, {"name": "gemma4:12b"}]},
                               post=lambda u, b, t: posts.append(b))
    assert out == ["qwen3-vl:8b"] and posts == [{"model": "qwen3-vl:8b", "keep_alive": 0}]


def test_routes_have_search_grant_and_activity_kinds():
    for r in ("/v1/models/route", "/v1/models/generate", "/v1/tools/list", "/v1/tools/call", "/v1/docs/search"):
        assert caller_auth.required_scope("POST", r) == "search"
        assert caller_auth.prefixed_route_allowed("POST", r, "grokbot")
    data = {"caller": {"caller_id": "grokbot"}, "model": "qwen3:8b", "target": "rackpc", "status": "done", "reason": "r"}
    assert agent_activity._summary("model.route", data) == "grokbot model qwen3:8b -> rackpc [done] (r)"
    assert "tool.call" in agent_activity.ALL_KINDS and "docs.search" in agent_activity.ALL_KINDS


def test_default_specs_scope_and_no_network_fetch():
    s = default_specs()
    assert set(s) == {"docs", "handoffs", "git", "memory", "time", "browser", "devtools"}
    assert s["docs"].args == [str(Path.home() / "Documents")] and "write_file" not in s["docs"].allow
    assert s["handoffs"].args[0].endswith("Documents/Jaeger-Handoffs") and "write_file" in s["handoffs"].allow
    assert "git_commit" not in s["git"].allow and "git_add" not in s["git"].allow
    b = s["browser"].args
    assert "--headless" in b and "--user-data-dir" in b and "http://127.0.0.1:8792" in b[b.index("--blocked-origins") + 1]
    assert "--port" not in b
    d = s["devtools"].args
    assert "--headless" in d and "--isolated" in d and "--javascriptEvaluation=false" in d
    assert any(a.startswith("chrome-devtools-mcp@") and a.split("@")[1][0].isdigit() for a in d)  # pinned
    assert "--autoConnect" not in d and "--user-data-dir" not in d and "Google Chrome.app" not in " ".join(d)
    assert "--chrome-arg=--proxy-server=http://127.0.0.1:9" in d
    assert "upload_file" not in s["devtools"].allow and "take_screenshot" in s["devtools"].allow


def test_pool_allowlist_refuses_before_spawn():
    pool = McpPool({"x": ServerSpec("x", "/nonexistent", [], frozenset({"ok"}))})
    with pytest.raises(ToolError) as e:
        asyncio.run(pool.call("x", "rm", {}))
    assert e.value.status == 403
    with pytest.raises(ToolError):
        asyncio.run(pool.call("nope", "t", {}))


@pytest.mark.skipif(not (Path.home() / ".local/bin/mcp-server-time").exists(), reason="mcp-server-time not installed")
def test_pool_real_time_server():
    async def go():
        pool = McpPool({"time": default_specs()["time"]})
        try:
            listed = await pool.list()
            out = await pool.call("time", "get_current_time", {"timezone": "UTC"})
            return listed, out
        finally:
            await pool.close()
    listed, out = asyncio.run(go())
    assert any(t["name"] == "get_current_time" for t in listed["time"]["tools"])
    assert not out["is_error"] and "UTC" in out["content"][0]["text"]


def test_docs_search_shapes_results_and_loopback_only(monkeypatch):
    calls = []

    def post(url, body, timeout=30):
        calls.append(url)
        if url.endswith("/api/embed"):
            return {"embeddings": [[0.1, 0.2]]}
        return {"result": {"points": [{"score": 0.9, "payload": {"path": "/a.md", "chunk": 0, "text": "hello"}}]}}
    out = docs.search("hello", 3, "/Users/x/Documents", post=post)
    assert out["results"][0]["path"] == "/a.md" and "data" in out["note"]
    assert calls[0].startswith("http://127.0.0.1:11434") and calls[1].startswith("http://127.0.0.1:6333")
    monkeypatch.setattr(docs, "QDRANT_URL", "http://10.0.0.5:6333")
    with pytest.raises(docs.DocsError):
        docs.search("hello", post=post)
    with pytest.raises(docs.DocsError):
        docs.search("", post=post)


def test_indexer_skips_secrets_hidden_and_chunks(tmp_path):
    root = tmp_path / "Documents"
    (root / ".hidden").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "notes.md").write_text("word " * 1000)
    (root / "api_token.txt").write_text("x" * 100)
    (root / ".hidden" / "a.md").write_text("x" * 100)
    (root / "node_modules" / "b.md").write_text("x" * 100)
    ix = docs_indexer.Indexer.__new__(docs_indexer.Indexer)
    ix.root = root
    assert [p.name for p in ix.candidates()] == ["notes.md"]
    c = docs_indexer.chunks("a" * 4000)
    assert len(c) == 4 and all(len(x) <= docs_indexer.CHUNK for x in c)


def test_mcp_tools_route_through_gateway():
    from jaeger_ai.features.agent_bridge import mcp as mod

    class M:
        tools = {}
        def tool(self, name=None):
            def deco(fn):
                self.tools[name or fn.__name__] = fn
                return fn
            return deco

    class C:
        calls = []
        def _call(self, m, p, b=None):
            self.calls.append((m, p, b)); return {"ok": True}

    m, c = M(), C()
    mp = pytest.MonkeyPatch()
    mp.setattr(mod, "enabled", lambda: None)
    mod.register(m, lambda ctx: c)
    asyncio.run(m.tools["jaeger.generate"]("hi"))
    asyncio.run(m.tools["jaeger.generate"]("hi", route_only=True))
    asyncio.run(m.tools["jaeger.tools"]())
    asyncio.run(m.tools["jaeger.tool"]("time", "get_current_time", {"timezone": "UTC"}))
    asyncio.run(m.tools["jaeger_search_docs"]("q"))
    assert [x[1] for x in c.calls] == ["/v1/models/generate", "/v1/models/route", "/v1/tools/list",
                                       "/v1/tools/call", "/v1/docs/search"]
    mp.undo()

@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.254",
    "192.168.1.1", "100.64.0.1", "100.127.255.254", "169.254.1.1",
    "::1", "fc00::1", "fdff::1", "fe80::1", "febf::1",
    "::ffff:127.0.0.1", "::ffff:192.168.1.1",
])
def test_browser_proxy_blocks_private_ranges(address):
    from jaeger_ai.features.oss_stack.browser_proxy import is_blocked_address
    assert is_blocked_address(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:4700:4700::1111", "::ffff:1.1.1.1"])
def test_browser_proxy_allows_public_addresses(address):
    from jaeger_ai.features.oss_stack.browser_proxy import is_blocked_address
    assert not is_blocked_address(address)


def test_browser_proxy_blocks_hostname_resolving_private():
    import socket
    from jaeger_ai.features.oss_stack.browser_proxy import DestinationBlocked, resolve_public

    def resolver(host, port, **kwargs):
        assert host == "private.example"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", port))]

    with pytest.raises(DestinationBlocked):
        resolve_public("private.example", 443, resolver)
    with pytest.raises(DestinationBlocked):
        resolve_public("localhost", 443, resolver)


def test_browser_spec_has_proxy_guard():
    args = default_specs()["browser"].args
    assert args[args.index("--proxy-server") + 1] == "http://127.0.0.1:0"
    assert args[args.index("--proxy-bypass") + 1] == "<-loopback>"
    assert "--blocked-origins" in args
