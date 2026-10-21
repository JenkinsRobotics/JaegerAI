"""Plugin extension API — third-party tools/commands/hooks.

Pin: the PluginContext collects registrations, fire_hook dispatches and
swallows buggy handlers, unknown hook events are rejected, and discovery is
graceful when there are no plugins.
"""

from __future__ import annotations

import pytest

from jaeger_ai.plugins import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


def test_context_collects_tools_commands_hooks():
    ctx = registry.context()
    ctx.register_tool("toolA")
    ctx.register_command("/weather", lambda arg: "sunny")
    ctx.register_hook("post_tool", lambda **kw: None)
    assert ctx.tools == ["toolA"]
    assert "weather" in ctx.commands           # leading slash stripped
    assert len(ctx.hooks["post_tool"]) == 1


def test_unknown_hook_event_is_rejected():
    with pytest.raises(ValueError):
        registry.context().register_hook("bogus", lambda: None)


def test_fire_hook_dispatches_and_swallows_buggy_handlers():
    calls: list[str] = []
    registry.context().register_hook(
        "pre_tool", lambda **kw: calls.append(kw.get("name")))
    registry.context().register_hook(
        "pre_tool", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    registry.fire_hook("pre_tool", name="web_search", data={})
    assert calls == ["web_search"]             # good ran; buggy swallowed


def test_discovery_is_graceful_without_plugins():
    assert registry.discover_plugins("nonexistent.group.xyz") == []


def _owned_entry(monkeypatch,register):
    from types import SimpleNamespace
    calls=[]
    entry=SimpleNamespace(name='owned-fixture',value='owned.fixture:register',dist=SimpleNamespace(name='owned-package',version='1'),load=lambda:(calls.append('load') or register))
    monkeypatch.setattr('importlib.metadata.entry_points',lambda **kw:[entry] if kw.get('group')=='jaeger_ai.plugins' else [])
    return calls


def test_catalog_never_loads_and_discovery_is_idempotent_with_hook_controls(monkeypatch):
    calls=[]
    loads=_owned_entry(monkeypatch,lambda ctx:ctx.register_hook('turn_end',lambda **kw:calls.append('hook')))
    initial=registry.catalog()['plugins'][0]
    assert initial['state']=='installed_not_loaded' and loads==[]
    assert registry.discover_plugins()==['owned-fixture']
    assert registry.discover_plugins()==['owned-fixture'] and loads==['load']
    current=registry.catalog()['plugins'][0]
    assert current['hook_count']==1
    registry.fire_hook('turn_end');assert calls==['hook']
    result=registry.control_hooks(current['id'],'pause_hooks','loaded')
    assert not result['code_unloaded'] and not result['tools_changed']
    registry.fire_hook('turn_end');assert calls==['hook']
    registry.control_hooks(current['id'],'resume_hooks','hooks_paused')
    registry.fire_hook('turn_end');assert calls==['hook','hook']
    with pytest.raises(ValueError):registry.control_hooks(current['id'],'pause_hooks','hooks_paused')


def test_registration_failure_discards_staged_context_and_never_replays(monkeypatch):
    def broken(ctx):
        ctx.register_command('partial',lambda:None)
        raise RuntimeError('after side effect')
    loads=_owned_entry(monkeypatch,broken)
    assert registry.discover_plugins()==[] and registry.discover_plugins()==[]
    assert loads==['load'] and 'partial' not in registry.context().commands
    assert registry.catalog()['plugins'][0]['state']=='registration_outcome_unknown'


def test_active_hook_blocks_pause_and_altered_distribution_cannot_overlay(monkeypatch):
    import threading
    started=threading.Event();release=threading.Event()
    def callback(**kw):started.set();assert release.wait(3)
    _owned_entry(monkeypatch,lambda ctx:ctx.register_hook('turn_end',callback))
    registry.discover_plugins();row=registry.catalog()['plugins'][0]
    thread=threading.Thread(target=registry.fire_hook,args=('turn_end',));thread.start()
    try:
        assert started.wait(2)
        with pytest.raises(ValueError,match='running'):registry.control_hooks(row['id'],'pause_hooks','loaded')
    finally:release.set();thread.join(3)
    registry.control_hooks(row['id'],'pause_hooks','loaded')
    from types import SimpleNamespace
    loaded=[]
    changed=SimpleNamespace(name='owned-fixture',value='owned.fixture:register',dist=SimpleNamespace(name='owned-package',version='2'),load=lambda:loaded.append('forbidden'))
    monkeypatch.setattr('importlib.metadata.entry_points',lambda **kw:[changed])
    assert registry.discover_plugins()==[] and loaded==[]


@pytest.mark.asyncio
async def test_plugin_http_scope_receipt_and_no_catalog_activation(tmp_path,monkeypatch):
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    loads=_owned_entry(monkeypatch,lambda ctx:ctx.register_hook('turn_end',lambda **kw:None))
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        catalog=await (await http.get('/v1/runtime/plugins')).json();assert not catalog['activation_performed'] and loads==[]
        registry.discover_plugins();row=registry.catalog()['plugins'][0]
        path='/v1/runtime/plugins/'+row['id']+'/pause_hooks'
        body={'operation_id':'owned-pause','expected_state':'loaded'}
        response=await http.post(path,json=body);assert response.status==200
        receipt=await response.json();assert receipt['result']['state']=='hooks_paused'
        assert await (await http.post(path,json=body)).json()==receipt
        assert (await http.post(path,json={**body,'operation_id':'owned-stale'})).status==409
        assert gateway.store.list_requests()==[]
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as http:
        assert (await http.get('/v1/runtime/plugins')).status==403
        assert (await http.post(path,json=body)).status==403


def test_package_revision_change_is_visible_and_cannot_resume_retained_code(monkeypatch):
    from types import SimpleNamespace
    loads=[]
    def entry(version):
        return SimpleNamespace(name='owned-fixture',value='owned.fixture:register',dist=SimpleNamespace(name='owned-package',version=version),load=lambda:(loads.append(version) or (lambda ctx:ctx.register_hook('turn_end',lambda **kw:None))))
    installed=[entry('1')]
    monkeypatch.setattr(registry,'_entries',lambda group:installed)
    registry.discover_plugins();old=registry.catalog()['plugins'][0]
    registry.control_hooks(old['id'],'pause_hooks','loaded')
    installed[:]=[entry('2')]
    rows=registry.catalog()['plugins'];retained=next(row for row in rows if row['id']==old['id']);candidate=next(row for row in rows if row['id']!=old['id'])
    assert retained['distribution_state']=='replaced' and retained['actions']==[]
    assert candidate['distribution_state']=='current' and candidate['activation_blocked_by_loaded_revision']
    assert old['id'] in candidate['related_revision_ids']
    with pytest.raises(ValueError,match='distribution changed'):
        registry.control_hooks(old['id'],'resume_hooks','hooks_paused')
    assert registry.discover_plugins()==[] and loads==['1']
    installed.clear()
    assert registry.catalog()['plugins'][0]['distribution_state']=='removed'
