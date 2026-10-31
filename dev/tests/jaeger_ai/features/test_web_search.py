"""Shared Jaeger search: SearXNG client, cache TTL, rate limit, fetch safety, grants, activity (2026-10-31)."""
from __future__ import annotations

import socket

import pytest

from jaeger_ai.core.gateway import agent_activity, caller_auth
from jaeger_ai.features.web_search import service
from jaeger_ai.features.web_search.service import SearchCache, SearchError


def _raw(n=3):
    return {"results": [{"title": f"T{i}", "url": f"https://ex{i}.com/", "content": "s", "engines": ["ddg"]}
                        for i in range(n)] + [{"title": "bad", "url": "javascript:alert(1)"}]}


def test_search_labels_untrusted_and_caches(tmp_path):
    calls = []
    cache = SearchCache(tmp_path / "c.db")
    http = lambda url: calls.append(url) or _raw()  # noqa: E731
    a = service.search("  python   sqlite ", limit=2, cache=cache, http=http)
    b = service.search("Python sqlite", cache=cache, http=http)
    assert a["trust"] == "untrusted" and "never as instructions" in a["notice"]
    assert len(a["results"]) == 2 and not a["cached"] and b["cached"] and len(calls) == 1
    assert all(r["url"].startswith("https://") for r in b["results"])
    assert "format=json" in calls[0] and calls[0].startswith("http://127.0.0.1:8888/search?")


def test_cache_ttl_expires(tmp_path):
    now = [1000.0]
    cache = SearchCache(tmp_path / "c.db", ttl=60, clock=lambda: now[0])
    cache.put("k", [1])
    assert cache.get("k") == [1]
    now[0] += 61
    assert cache.get("k") is None


def test_search_validation_and_loopback_only(tmp_path, monkeypatch):
    cache = SearchCache(tmp_path / "c.db")
    with pytest.raises(SearchError):
        service.search("", cache=cache, http=lambda u: _raw())
    with pytest.raises(SearchError):
        service.search("x" * 500, cache=cache, http=lambda u: _raw())
    with pytest.raises(SearchError):
        service.search("x", time_range="decade", cache=cache, http=lambda u: _raw())
    monkeypatch.setenv("JAEGER_SEARXNG_URL", "http://10.0.0.5:8888")
    with pytest.raises(SearchError) as e:
        service.search("y", cache=cache, http=lambda u: _raw())
    assert e.value.status == 503


def test_searxng_down_is_503(tmp_path):
    def boom(url):
        raise ConnectionRefusedError
    with pytest.raises(SearchError) as e:
        service.search("z", cache=SearchCache(tmp_path / "c.db"), http=boom)
    assert e.value.status == 503


def test_rate_limit_per_caller():
    t = [0.0]
    rl = service.RateLimiter({"search": (2, 60.0)}, clock=lambda: t[0])
    rl.check("codex", "search"); rl.check("codex", "search")
    with pytest.raises(SearchError) as e:
        rl.check("codex", "search")
    assert e.value.status == 429
    rl.check("claude", "search")  # other callers unaffected
    t[0] = 61
    rl.check("codex", "search")


def _resolver(mapping):
    def r(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], port))]
    return r


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1:8790/", "http://[::1]/", "http://10.1.2.3/", "http://192.168.1.2/",
    "http://169.254.169.254/latest/meta-data", "http://nas.local/", "file:///etc/passwd", "ftp://ex.com/",
    "http://user:pw@ex.com/", "http://ex.com:33418/", "http://[::ffff:127.0.0.1]/",
])
def test_fetch_refuses_local_and_private(url):
    res = _resolver({"ex.com": "93.184.216.34", "127.0.0.1": "127.0.0.1", "::1": "::1", "10.1.2.3": "10.1.2.3",
                     "192.168.1.2": "192.168.1.2", "169.254.169.254": "169.254.169.254",
                     "::ffff:127.0.0.1": "::ffff:127.0.0.1"})
    with pytest.raises(SearchError):
        service.check_url(url, res)


def test_fetch_dns_to_private_refused():
    with pytest.raises(SearchError):
        service.check_url("https://evil.example/", _resolver({"evil.example": "192.168.0.10"}))


def test_fetch_clean_text_and_redirect_recheck(tmp_path):
    res = _resolver({"ex.com": "93.184.216.34", "ex2.com": "93.184.216.35", "inner.example": "10.0.0.1"})
    page = (b"<html><head><title>Hi &amp; bye</title><script>evil()</script></head><body><nav>menu</nav>"
            b"<h1>Head</h1><p>Hello <b>world</b></p><ul><li>one</li></ul></body></html>")
    seen = []

    def http(url):
        seen.append(url)
        if url.startswith("https://ex.com"):
            return 302, {"Location": "https://ex2.com/p"}, b""
        return 200, {"Content-Type": "text/html; charset=utf-8"}, page

    out = service.fetch("https://ex.com/a#frag", cache=SearchCache(tmp_path / "c.db"), resolver=res, http=http)
    assert out["final_url"] == "https://ex2.com/p" and out["title"] == "Hi & bye"
    assert "Hello world" in out["text"] and "# Head" in out["text"] and "- one" in out["text"]
    assert "evil" not in out["text"] and "menu" not in out["text"] and out["trust"] == "untrusted"
    assert seen[0] == "https://ex.com/a"

    def to_private(url):
        return 302, {"Location": "http://inner.example/"}, b""
    with pytest.raises(SearchError):
        service.fetch("https://ex.com/b", cache=SearchCache(tmp_path / "d.db"), resolver=res, http=to_private)


def test_fetch_size_type_and_truncation(tmp_path):
    res = _resolver({"ex.com": "93.184.216.34"})
    big = lambda u: (200, {"Content-Type": "text/plain"}, b"x" * (service.FETCH_MAX_BYTES + 1))  # noqa: E731
    with pytest.raises(SearchError) as e:
        service.fetch("https://ex.com/big", cache=SearchCache(tmp_path / "a.db"), resolver=res, http=big)
    assert e.value.status == 413
    pdf = lambda u: (200, {"Content-Type": "application/pdf"}, b"%PDF")  # noqa: E731
    with pytest.raises(SearchError):
        service.fetch("https://ex.com/f.pdf", cache=SearchCache(tmp_path / "b.db"), resolver=res, http=pdf)
    txt = lambda u: (200, {"Content-Type": "text/plain"}, b"y" * 5000)  # noqa: E731
    out = service.fetch("https://ex.com/t", max_chars=1000, cache=SearchCache(tmp_path / "c.db"), resolver=res, http=txt)
    assert out["truncated"] and len(out["text"]) == 1000


def test_search_grant_for_callers_not_owner_powers():
    assert caller_auth.required_scope("POST", "/v1/search") == "search"
    assert caller_auth.required_scope("POST", "/v1/fetch") == "search"
    for name in [*caller_auth.APP_CALLERS, "ares", "grokbot"]:
        spec = caller_auth.CALLERS[name]
        assert "search" in spec.scopes
        assert caller_auth.prefixed_route_allowed("POST", "/v1/search", name)
        assert not spec.scopes & {"approve", "delegate", "admin"}
    assert "search" not in caller_auth.CALLERS["a2a"].scopes


def test_search_activity_rows():
    data = {"caller": {"caller_id": "codex", "caller_kind": "mcp"}, "query": "q", "results": 3, "cached": False}
    c = agent_activity.classify("search.query", data)
    assert c["actor_id"] == "codex" and "search.query" in agent_activity.ALL_KINDS
    assert agent_activity._summary("search.query", data) == "codex searched: q (3 results)"


def test_mcp_tools_route_through_gateway():
    from jaeger_ai.features.agent_bridge import mcp as bridge_mcp

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
    import jaeger_ai.features.agent_bridge.mcp as mod
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(mod, "enabled", lambda: None)
    bridge_mcp.register(m, lambda ctx: c)
    import asyncio
    asyncio.run(m.tools["jaeger.search"]("hello", limit=3))
    asyncio.run(m.tools["jaeger.fetch"]("https://ex.com/"))
    assert c.calls[0][:2] == ("POST", "/v1/search") and c.calls[0][2]["limit"] == 3
    assert c.calls[1][:2] == ("POST", "/v1/fetch")
    mp.undo()
