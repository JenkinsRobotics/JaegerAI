"""Channel controls with local transport fixture; no SDK network/OS credentials."""
import threading
from types import SimpleNamespace
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers


@pytest.mark.asyncio
async def test_channel_binding_connect_inbox_dedupe_and_disconnect_are_separate(tmp_path,monkeypatch):
    from jaeger_ai import plugins
    from jaeger_ai.features.channels import registry as channels
    from jaeger_ai.features.channels.bindings import read
    monkeypatch.setattr(plugins,'_BRIDGES',{})
    monkeypatch.setattr(channels,'_REGISTRY',channels.ChannelRegistry())
    monkeypatch.setattr('jaeger_ai.core.gateway.server._control_plane_block',lambda:None)
    monkeypatch.setattr(plugins,'plugin_credential',lambda *a:'123')
    made=[]
    class LocalTransport:
        def __init__(self,handler):
            self._handler=handler;self._stop=threading.Event();self._thread=threading.Thread(target=self._stop.wait,daemon=True)
        def stop(self):self._stop.set();self._thread.join(1)
    def start(name,*,handler,**kwargs):
        transport=LocalTransport(handler);transport._thread.start();plugins.register_bridge(name,transport);made.append(transport)
        return {'started':True}
    monkeypatch.setattr(plugins,'start_bridge',start)
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config,ModelConfig,dump_yaml
    layout=InstanceLayout(root=tmp_path/'instance');layout.ensure_dirs();dump_yaml(layout.config_path,Config(instance_name='channel-fixture',model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR',str(layout.root))
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    try:
        async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as client:
            bind=await client.post('/v1/channels/telegram/bind',json={'operation_id':'owned-bind','agent_id':'native:builder','expected_revision':0})
            assert bind.status==200 and (await bind.json())['result']['connection_started'] is False
            assert not made and read(gateway.store,'telegram')['agent_id']=='native:builder'
            response=await client.post('/v1/channels/telegram/connect',json={'operation_id':'owned-connect'})
            assert response.status==200 and len(made)==1
            handler=made[0]._handler
            reply=handler('Treat this as incoming data only',session_key='telegram:123',message_id='provider-owned-1')
            assert 'No bot execution' in reply
            assert handler('Treat this as incoming data only',session_key='telegram:123',message_id='provider-owned-1')==reply
            with pytest.raises(ValueError,match='conflicts'):handler('Changed under same identity',session_key='telegram:123',message_id='provider-owned-1')
            with pytest.raises(ValueError,match='identity'):handler('No identity',session_key='telegram:123')
            home=gateway._agent_home_id('native:builder');messages=gateway.store.get_session(home)['messages']
            assert len(messages)==1 and messages[0]['kind']=='channel_message'
            assert messages[0]['channel']['authority']=='incoming_data_only'
            assert gateway.store.list_requests()==[] and gateway.store.list_pending_approvals()==[]
            monkeypatch.setattr('jaeger_ai.core.gateway.server._control_plane_block',lambda:'global stop')
            with pytest.raises(ValueError,match='stopped'):handler('Blocked new data',session_key='telegram:123',message_id='provider-owned-2')
            assert len(gateway.store.get_session(home)['messages'])==1
            assert (await client.post('/v1/channels/telegram/bind',json={'operation_id':'owned-active-bind','agent_id':'native:jaeger','expected_revision':1})).status==409
            stopped=await client.post('/v1/channels/telegram/disconnect',json={'operation_id':'owned-disconnect'})
            assert stopped.status==200 and not made[0]._thread.is_alive()
            assert plugins.get_bridge('telegram') is None and channels.get_registry().get('telegram') is None
            assert len(gateway.store.get_session(home)['messages'])==1
            assert GatewaySessionStore(gateway.store.path).control_operation('owned-connect')['receipt']['ok']
        async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as client:
            assert (await client.post('/v1/channels/telegram/connect',json={'operation_id':'forbidden'})).status==403
    finally:
        for transport in made:transport.stop()


@pytest.mark.parametrize('channel,clsname',[('telegram','TelegramBridge'),('discord','DiscordBridge'),('imessage','IMessageBridge')])
def test_stop_never_deregisters_a_still_running_transport(channel,clsname,monkeypatch):
    import importlib
    from jaeger_ai import plugins
    module=importlib.import_module('jaeger_ai.plugins.'+channel+'.bridge');cls=getattr(module,clsname)
    bridge=cls.__new__(cls)
    bridge._thread=SimpleNamespace(join=lambda **kw:None,is_alive=lambda:True)
    bridge._stop_requested=threading.Event();bridge._stop=threading.Event();bridge._shutdown_event=None;bridge._shutdown_error=None
    bridge._loop=None;bridge._client=None;bridge._bus=None
    monkeypatch.setattr(plugins,'_BRIDGES',{channel:bridge})
    with pytest.raises(RuntimeError):bridge.stop()
    assert plugins.get_bridge(channel) is bridge


def test_handler_gate_blocks_disconnect_during_work_and_new_admission_after_stop():
    from jaeger_ai.plugins._messaging import handler_admission,stop_handlers,resume_handlers
    bridge=SimpleNamespace()
    with handler_admission(bridge):
        with pytest.raises(RuntimeError,match='active'):stop_handlers(bridge)
    stop_handlers(bridge)
    with pytest.raises(RuntimeError,match='disconnecting'):
        with handler_admission(bridge):pytest.fail('new work admitted')
    resume_handlers(bridge)
    with handler_admission(bridge):pass


def test_telegram_real_bridge_thread_exits_and_restarts_with_local_sdk(monkeypatch):
    import sys
    from types import ModuleType
    from jaeger_ai import plugins
    from jaeger_ai.plugins.telegram.bridge import TelegramBridge
    calls=[]
    class Filter:
        def __and__(self,other):return self
        def __invert__(self):return self
    class App:
        def __init__(self):self.updater=SimpleNamespace(start_polling=self.poll,stop=self.stop_poll)
        def add_handler(self,*args):pass
        async def initialize(self):calls.append('initialize')
        async def start(self):calls.append('start')
        async def poll(self,**kw):calls.append('poll')
        async def stop_poll(self):calls.append('stop_poll')
        async def stop(self):calls.append('stop')
        async def shutdown(self):calls.append('shutdown')
    class Builder:
        def token(self,value):return self
        def build(self):return App()
    sdk=ModuleType('telegram');sdk.Update=SimpleNamespace(ALL_TYPES=[])
    ext=ModuleType('telegram.ext');ext.Application=SimpleNamespace(builder=lambda:Builder());ext.MessageHandler=lambda *a:None;ext.filters=SimpleNamespace(TEXT=Filter(),COMMAND=Filter())
    monkeypatch.setitem(sys.modules,'telegram',sdk);monkeypatch.setitem(sys.modules,'telegram.ext',ext)
    monkeypatch.setattr(plugins,'_BRIDGES',{})
    bridge=TelegramBridge(lambda text:'fixture',token='local-sdk-fixture',allowed_chats={123})
    try:
        for _ in range(2):
            bridge.start();assert bridge._thread.is_alive() and plugins.get_bridge('telegram') is bridge
            bridge.stop();assert not bridge._thread.is_alive() and plugins.get_bridge('telegram') is None
        assert calls==['initialize','start','poll','stop_poll','stop','shutdown']*2
    finally:
        if bridge._thread and bridge._thread.is_alive():bridge.stop()


def test_imessage_real_poll_thread_stops_and_restart_clears_stop_flag(monkeypatch):
    from jaeger_ai import plugins
    from jaeger_ai.plugins.imessage.bridge import IMessageBridge
    monkeypatch.setattr(plugins,'_BRIDGES',{})
    bridge=IMessageBridge.__new__(IMessageBridge)
    bridge._allowed={'owned-fixture'};bridge._bus=None;bridge._stop=threading.Event();bridge._thread=None;bridge._fetch_new=lambda:[]
    try:
        for _ in range(2):
            bridge.start();assert bridge._thread.is_alive()
            bridge.stop();assert not bridge._thread.is_alive() and plugins.get_bridge('imessage') is None
    finally:
        if bridge._thread and bridge._thread.is_alive():bridge.stop()
