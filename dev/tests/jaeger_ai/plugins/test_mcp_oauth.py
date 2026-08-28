"""MCP OAuth — token storage, provider reuse, and 401 de-duplication.

Ported from hermes-agent ``tools/mcp_oauth_manager.py``. The two behaviours
pinned hardest are the ones that only appear under real use: a token
refreshed by another process must be picked up without a restart, and N
concurrent 401s must trigger exactly one recovery.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from jaeger_ai.plugins.mcp import oauth


@pytest.fixture()
def layout(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.instance import InstanceLayout

    lay = InstanceLayout(root=tmp_path)
    lay.credentials_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("jaeger_agent.workspace.get_layout", lambda: lay)
    oauth.reset_manager()
    yield lay
    oauth.reset_manager()


def _token(access="tok-1", refresh="ref-1"):
    from mcp.shared.auth import OAuthToken

    return OAuthToken(access_token=access, token_type="Bearer",
                      refresh_token=refresh, expires_in=3600)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def test_round_trip(layout):
    st = oauth.FileTokenStorage("srv")
    assert asyncio.run(st.get_tokens()) is None
    asyncio.run(st.set_tokens(_token()))
    got = asyncio.run(st.get_tokens())
    assert got.access_token == "tok-1"


def test_tokens_are_written_0600(layout):
    st = oauth.FileTokenStorage("srv")
    asyncio.run(st.set_tokens(_token()))
    path = oauth.token_dir() / "srv.json"
    assert oct(path.stat().st_mode)[-3:] == "600"


@pytest.mark.parametrize("name", ["../../evil", "..", ".", "a/b/c", "x\\y"])
def test_server_name_cannot_escape_the_token_dir(layout, name):
    """The property is containment, not cosmetics: separators become plain
    characters, so the file always lands inside the token directory."""
    st = oauth.FileTokenStorage(name)
    asyncio.run(st.set_tokens(_token()))
    files = [p for p in oauth.token_dir().glob("*.json")]
    assert files, "token file was not written"
    for f in files:
        assert f.resolve().parent == oauth.token_dir().resolve()


def test_corrupt_token_file_reads_as_absent(layout):
    st = oauth.FileTokenStorage("srv")
    asyncio.run(st.set_tokens(_token()))
    (oauth.token_dir() / "srv.json").write_text("{ broken", encoding="utf-8")
    st2 = oauth.FileTokenStorage("srv")
    assert asyncio.run(st2.get_tokens()) is None


def test_external_refresh_is_picked_up(layout):
    """Another process rewrote the file — we must not serve the stale token."""
    st = oauth.FileTokenStorage("srv")
    asyncio.run(st.set_tokens(_token("old")))
    assert asyncio.run(st.get_tokens()).access_token == "old"

    path = oauth.token_dir() / "srv.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["access_token"] = "rotated-elsewhere"
    # Force a distinct mtime so the change is observable on coarse clocks.
    path.write_text(json.dumps(data), encoding="utf-8")
    os.utime(path, (0, 0))

    assert asyncio.run(st.get_tokens()).access_token == "rotated-elsewhere"


def test_disk_changed_detects_external_writes(layout):
    st = oauth.FileTokenStorage("srv")
    asyncio.run(st.set_tokens(_token()))
    assert st.disk_changed() is False
    os.utime(oauth.token_dir() / "srv.json", (0, 0))
    assert st.disk_changed() is True


def test_client_info_round_trip(layout):
    from mcp.shared.auth import OAuthClientInformationFull

    st = oauth.FileTokenStorage("srv")
    info = OAuthClientInformationFull(
        client_id="abc", redirect_uris=["http://localhost:8765/callback"])
    asyncio.run(st.set_client_info(info))
    assert asyncio.run(st.get_client_info()).client_id == "abc"


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

def test_provider_is_constructed_once_per_server(layout):
    m = oauth.get_manager()
    a = m.provider("srv", "https://example.test/mcp")
    b = m.provider("srv", "https://example.test/mcp")
    assert a is b


def test_separate_servers_get_separate_providers(layout):
    m = oauth.get_manager()
    assert m.provider("a", "https://a.test") is not m.provider("b", "https://b.test")


def test_provider_rebuilt_when_tokens_change_on_disk(layout):
    m = oauth.get_manager()
    first = m.provider("srv", "https://example.test/mcp")
    st = m._storages["srv"]
    asyncio.run(st.set_tokens(_token()))
    os.utime(oauth.token_dir() / "srv.json", (0, 0))
    assert m.provider("srv", "https://example.test/mcp") is not first


def test_forget_drops_state(layout):
    m = oauth.get_manager()
    first = m.provider("srv", "https://example.test/mcp")
    m.forget("srv")
    assert m.provider("srv", "https://example.test/mcp") is not first


# ---------------------------------------------------------------------------
# 401 de-duplication
# ---------------------------------------------------------------------------

def test_concurrent_recoveries_run_once(layout):
    m = oauth.get_manager()
    calls = {"n": 0}

    async def recover():
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return "fresh-token"

    async def main():
        return await asyncio.gather(
            *(m.recover_once("srv", recover) for _ in range(8)))

    results = asyncio.run(main())
    assert calls["n"] == 1
    assert results == ["fresh-token"] * 8


def test_a_later_recovery_runs_again(layout):
    m = oauth.get_manager()
    calls = {"n": 0}

    async def recover():
        calls["n"] += 1
        return calls["n"]

    async def main():
        await m.recover_once("srv", recover)
        await m.recover_once("srv", recover)

    asyncio.run(main())
    assert calls["n"] == 2


def test_recovery_failure_propagates_to_every_waiter(layout):
    m = oauth.get_manager()

    async def recover():
        await asyncio.sleep(0.02)
        raise RuntimeError("refresh rejected")

    async def main():
        return await asyncio.gather(
            *(m.recover_once("srv", recover) for _ in range(4)),
            return_exceptions=True)

    results = asyncio.run(main())
    assert len(results) == 4
    assert all(isinstance(r, RuntimeError) for r in results)


def test_recovery_state_is_per_server(layout):
    m = oauth.get_manager()
    calls: list[str] = []

    def make(name):
        async def recover():
            calls.append(name)
            await asyncio.sleep(0.02)
            return name
        return recover

    async def main():
        return await asyncio.gather(
            m.recover_once("a", make("a")), m.recover_once("b", make("b")))

    assert set(asyncio.run(main())) == {"a", "b"}
    assert sorted(calls) == ["a", "b"]


# ---------------------------------------------------------------------------
# Config plumbing
# ---------------------------------------------------------------------------

def test_server_uses_oauth_detection():
    from jaeger_ai.plugins.mcp.client import MCPServerConfig

    assert oauth.server_uses_oauth(MCPServerConfig(name="s", auth="oauth"))
    assert oauth.server_uses_oauth(MCPServerConfig(name="s", auth="OAuth2"))
    assert not oauth.server_uses_oauth(MCPServerConfig(name="s"))
    assert not oauth.server_uses_oauth(MCPServerConfig(name="s", auth="bearer"))


def test_config_defaults_keep_static_header_servers_unchanged():
    from jaeger_ai.plugins.mcp.client import MCPServerConfig

    cfg = MCPServerConfig(name="s", url="https://x.test",
                          headers={"Authorization": "Bearer t"})
    assert cfg.auth == ""
    assert oauth.server_uses_oauth(cfg) is False
