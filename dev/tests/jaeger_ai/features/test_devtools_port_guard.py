"""DevTools browser may reach only the WebUI port on loopback; never the hub, gateway or public sites."""
import asyncio

import pytest

from jaeger_ai.features.oss_stack import mcp_pool
from jaeger_ai.features.oss_stack.browser_proxy import DestinationBlocked, resolve_destination, start_proxy


def test_devtools_allows_only_webui_loopback_port():
    assert mcp_pool.DEVTOOLS_LOOPBACK_PORTS == frozenset({8790})
    ports = mcp_pool.DEVTOOLS_LOOPBACK_PORTS
    assert resolve_destination("127.0.0.1", 8790, loopback_ports=ports, public=False)[4] == ("127.0.0.1", 8790)
    assert resolve_destination("localhost", 8790, loopback_ports=ports, public=False)[4] == ("127.0.0.1", 8790)
    for host in ("127.0.0.1", "localhost", "[::1]"):
        for port in (8792, 33418, 8791, 8793, 11434, 5678):
            with pytest.raises(DestinationBlocked):
                resolve_destination(host, port, loopback_ports=ports, public=False)
    with pytest.raises(DestinationBlocked):
        resolve_destination("example.com", 443, loopback_ports=ports, public=False)


def test_devtools_routes_loopback_through_guard():
    args = mcp_pool.default_specs()["devtools"].args
    assert "--chrome-arg=--proxy-bypass-list=<-loopback>" in args
    assert not any("localhost;127.0.0.1" in a for a in args)


def test_shared_browser_guard_unchanged():
    with pytest.raises(DestinationBlocked):
        resolve_destination("127.0.0.1", 8790)


def test_guard_proxy_refuses_hub_and_gateway_live():
    async def run():
        proxy = await start_proxy(loopback_ports=frozenset({8790}), public=False)
        port = proxy.sockets[0].getsockname()[1]
        out = []
        for target in ("127.0.0.1:8792", "127.0.0.1:33418", "localhost:8792"):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
            await w.drain()
            out.append(await r.readline())
            w.close()
        proxy.close()
        await proxy.wait_closed()
        return out
    assert all(line.startswith(b"HTTP/1.1 403") for line in asyncio.run(run()))
