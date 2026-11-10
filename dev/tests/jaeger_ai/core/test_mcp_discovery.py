"""MCP paginated snapshots and listChanged reconciliation, no external services."""
import asyncio
from types import SimpleNamespace as NS
import pytest
from jaeger_ai.plugins.mcp import client as mcp
from jaeger_os.core.tools import tool_registry as registry
from jaeger_os.core.safety.permissions import PermissionPolicy, use_policy


def tool(name, description='Fixture'):
    return NS(name=name,description=description,inputSchema={'type':'object','properties':{}})

@pytest.mark.asyncio
async def test_all_pages_and_repeated_cursor_rejected():
    client=mcp._MCPClient(mcp.MCPServerConfig('fixture'))
    cursors=[]
    async def listing(cursor=None):
        cursors.append(cursor)
        return NS(tools=[tool('a' if cursor is None else 'b')],nextCursor='next' if cursor is None else None)
    client._session=NS(list_tools=listing)
    assert [t.name for t in await client.list_tools()]==['a','b']
    assert cursors==[None,'next']
    async def broken(cursor=None): return NS(tools=[],nextCursor='same')
    client._session=NS(list_tools=broken)
    with pytest.raises(ValueError,match='cursor'): await client.list_tools()

@pytest.fixture
def inventory(monkeypatch):
    class SDK:
        def __init__(self,config): self.config=config;self.offered=[tool('a'),tool('b')]
        async def connect(self): return self.offered
        async def list_tools(self): return self.offered
        async def close(self,**kwargs): pass
        async def call(self,*args): return NS(content=[],isError=False)
    monkeypatch.setattr(mcp,'_MCPClient',SDK)
    reg=mcp.MCPRegistry()
    reg.add_server(mcp.MCPServerConfig('discovery-fixture',tools_read_only=['*']))
    yield reg
    reg.shutdown();reg._loop.close()


def refresh(reg):
    async def run():
        reg._schedule_refresh('discovery-fixture')
        await reg._refresh_tasks['discovery-fixture']
    reg._submit(run(),timeout=3)


def test_changed_and_removed_tools_replace_atomically_and_old_handles_refuse(inventory):
    name='discovery-fixture'
    old=registry.get_tool('mcp__discovery-fixture__a')
    inventory._clients[name].offered=[tool('a','New schema description'),tool('c')]
    refresh(inventory)
    assert not registry.has_tool('mcp__discovery-fixture__b')
    assert registry.get_tool('mcp__discovery-fixture__a').description=='New schema description'
    assert registry.has_tool('mcp__discovery-fixture__c')
    with use_policy(PermissionPolicy()):
        with pytest.raises(ValueError,match='inventory changed'): old.fn()
    assert inventory._inventory_versions[name]==2


def test_bad_refresh_keeps_whole_previous_inventory(inventory):
    name='discovery-fixture'
    inventory._clients[name].offered=[tool('same.a'),tool('same/a')]
    refresh(inventory)
    assert {s.tool_name for s in inventory.list_tools()}=={'a','b'}
    assert name in inventory._inventory_errors
    assert not registry.has_tool('mcp__discovery-fixture__same_a')


def test_refresh_waits_for_active_calls_and_coalesces_notifications(inventory):
    name='discovery-fixture'
    async def run():
        inventory._active_calls[name]=1
        inventory._clients[name].offered=[tool('new')]
        inventory._schedule_refresh(name)
        inventory._schedule_refresh(name)
        await asyncio.sleep(.12)
        assert {s.tool_name for s in inventory.list_tools()}=={'a','b'}
        inventory._active_calls[name]=0
        await inventory._refresh_tasks[name]
    inventory._submit(run(),timeout=3)
    assert {s.tool_name for s in inventory.list_tools()}=={'new'}


def test_owner_declared_permission_metadata(inventory):
    assert registry.get_tool('mcp__discovery-fixture__a').permission_tier=='READ_ONLY'
    spec=mcp.MCPToolSpec('mcp:x/y','x','y','',{},'mcp__x__y')
    assert mcp._agent_tool_def(spec).permission_tier=='EXTERNAL_EFFECT'


def test_real_sdk_list_changed_notification_reconciles_inventory(tmp_path):
    import sys, textwrap, time
    server=tmp_path/'inventory_server.py'
    server.write_text(textwrap.dedent('''
        from mcp.server.fastmcp import FastMCP, Context
        app=FastMCP('isolated-discovery-fixture')
        @app.tool()
        async def change_inventory(ctx: Context) -> str:
            @app.tool()
            def added_tool() -> str:
                return 'fixture only'
            await ctx.session.send_tool_list_changed()
            return 'changed'
        app.run('stdio')
    '''))
    reg=mcp.MCPRegistry()
    try:
        reg.add_server(mcp.MCPServerConfig('sdk-discovery-fixture',command=sys.executable,args=[str(server)]))
        reg.call('mcp:sdk-discovery-fixture/change_inventory',{})
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not reg.has_tool('mcp:sdk-discovery-fixture/added_tool'):
            time.sleep(.05)
        assert reg.has_tool('mcp:sdk-discovery-fixture/added_tool')
        assert registry.has_tool('mcp__sdk-discovery-fixture__added_tool')
        assert reg._inventory_versions['sdk-discovery-fixture']==2
    finally:
        reg.shutdown();reg._loop.close()
