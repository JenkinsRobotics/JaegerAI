"""Loaded registry lifecycle with isolated SDK stand-ins; no connections/credentials."""
import asyncio
import threading
from types import SimpleNamespace
import pytest
from jaeger_ai.plugins.mcp import client as mcp


@pytest.fixture
def registry(monkeypatch):
    class LocalSDK:
        def __init__(self,config): self.config=config;self.closed=False;self.fail_close=False
        async def connect(self): return [SimpleNamespace(name='owned_read',description='fixture',inputSchema={})]
        async def close(self,*,strict=False):
            if strict and self.fail_close: raise RuntimeError('Fixture close failed')
            self.closed=True
        async def call(self,*args): return SimpleNamespace(content=[],isError=False)
    monkeypatch.setattr(mcp,'_MCPClient',LocalSDK)
    registry=mcp.MCPRegistry()
    registry.add_server(mcp.MCPServerConfig('owned-lifecycle-fixture'))
    monkeypatch.setattr(mcp,'_GLOBAL_REGISTRY',registry)
    yield registry
    registry.shutdown()
    registry._loop.close()


def test_disconnect_reconnect_reuses_unchanged_config_and_removes_tools(registry):
    name='owned-lifecycle-fixture';cid=registry.control_id(name);original=registry._clients[name]
    snapshot=mcp.runtime_inventory()['servers'][0]
    assert snapshot['id']==cid and snapshot['actions']==['disconnect']
    result=registry.lifecycle(cid,'disconnect','loaded_not_probed')
    assert result['state']=='disconnected' and original.closed
    assert not registry.list_tools() and name not in registry._clients
    assert mcp.runtime_inventory()['servers'][0]['actions']==['reconnect']
    registry.lifecycle(cid,'reconnect','disconnected')
    assert registry._clients[name].config is original.config
    assert len(registry.list_tools())==1 and mcp.runtime_inventory()['servers'][0]['state']=='loaded_not_probed'


def test_live_call_and_failed_close_cannot_claim_disconnected(registry):
    name='owned-lifecycle-fixture';cid=registry.control_id(name)
    entered,release=threading.Event(),threading.Event()
    async def call(*args):
        entered.set()
        while not release.is_set(): await asyncio.sleep(.01)
        return SimpleNamespace(content=[],isError=False)
    registry._clients[name].call=call
    thread=threading.Thread(target=lambda:registry.call(f'mcp:{name}/owned_read',{}));thread.start()
    assert entered.wait(2)
    try:
        with pytest.raises(ValueError,match='active'):
            registry.lifecycle(cid,'disconnect','loaded_not_probed')
        assert mcp.runtime_inventory()['servers'][0]['actions']==[]
    finally:release.set();thread.join(2)
    assert not thread.is_alive()
    registry._clients[name].fail_close=True
    with pytest.raises(RuntimeError,match='unknown'):
        registry.lifecycle(cid,'disconnect','loaded_not_probed')
    assert name in registry._clients and registry.list_tools()
    assert mcp.runtime_inventory()['servers'][0]['state']=='outcome_unknown'
    with pytest.raises(RuntimeError,match='reconciliation'):
        registry.call(f'mcp:{name}/owned_read',{})
    with pytest.raises(ValueError):registry.lifecycle(cid,'reconnect','outcome_unknown')


@pytest.mark.asyncio
async def test_http_controls_scope_receipt_and_stale_state(registry,tmp_path):
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    cid=registry.control_id('owned-lifecycle-fixture');url=f'/v1/runtime/mcp/{cid}/disconnect'
    body={'operation_id':'owned-mcp-disconnect','expected_state':'loaded_not_probed'}
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as client:
        assert (await client.post(url,json=body)).status==403
        assert registry._server_states=={}
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as client:
        first=await client.post(url,json=body);assert first.status==200
        receipt=await first.json();assert receipt['ok'] and receipt['result']['state']=='disconnected'
        assert await (await client.post(url,json=body)).json()==receipt
        assert (await client.post(url,json={**body,'operation_id':'owned-stale'})).status==409
        lookup=await (await client.get('/v1/control-operations/owned-mcp-disconnect')).json()
        assert lookup['receipt']==receipt
        assert gateway.store.list_requests()==[]


def test_unknown_resource_operation_blocks_fresh_ids_after_store_reopen(tmp_path):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    store=GatewaySessionStore(tmp_path/'gateway.sqlite3')
    assert store.reserve_scoped_control_operation('unknown-owned',{'action':'disconnect'},'mcp:owned')
    reopened=GatewaySessionStore(store.path)
    assert not reopened.reserve_scoped_control_operation('unknown-owned',{'action':'disconnect'},'mcp:owned')
    with pytest.raises(ValueError,match='Earlier resource operation'):
        reopened.reserve_scoped_control_operation('fresh-owned',{'action':'reconnect'},'mcp:owned')
    assert reopened.control_operation('fresh-owned') is None
    assert reopened.reserve_scoped_control_operation('independent-owned',{'action':'disconnect'},'mcp:other')
