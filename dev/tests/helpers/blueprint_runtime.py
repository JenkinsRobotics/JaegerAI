"""Owned integration fixture: real Gateway/proxy/tools; deterministic model boundary.

Never production ports/state; existing caller authentication and lifecycle guards
remain. No external connections, credentials created, policy grants or installs.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import threading


async def main(state: Path, ui_dist: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    state = state.expanduser().resolve()
    fixture_root = (Path.home()/'.cache/jaeger/fixtures').resolve()
    # The pytest live-state guard watches all of ~/.jaeger, including its old
    # verification subtree. Concurrent browser fixture writes must stay outside
    # that tree; do not exclude them or weaken the guard.
    if state == fixture_root or state.is_relative_to(repo) or not state.is_relative_to(fixture_root):
        raise RuntimeError('Require an owned ~/.cache/jaeger/fixtures/blueprint-* fixture root')
    if not state.name.startswith('blueprint-'):
        raise RuntimeError('Require an explicitly named blueprint fixture')
    source_sha = {name: hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in [
        'jaeger_ai/core/gateway/server.py', 'jaeger_ai/core/gateway/turn_parts.py',
        'jaeger_ai/contract/tool_outcomes.py', 'jaeger_ai/features/webui/api/jaeger_sessions.py']}
    state.mkdir(parents=True, exist_ok=True)
    if (state/'gateway_sessions.sqlite3').exists():
        raise RuntimeError('Use a fresh unique fixture state; never replay a prior test')
    os.environ.update(JAEGER_STATE_DIR=str(state), JAEGER_HOME=str(state), JAEGER_INSTANCE_DIR=str(state/'instances/fixture'),
                      HERMES_HOME=str(state/'webui-agent'), HERMES_WEBUI_STATE_DIR=str(state/'webui'),
                      HERMES_WEBUI_DEFAULT_WORKSPACE=str(state/'instances/fixture/workspace'),
                      JAEGER_NO_ATTACH='1', JAEGER_NO_GUI='1', JAEGER_TEST_HEADLESS='1', JAEGER_RUNTIME_MODE='owner',
                      JAEGER_CALLER_TOKEN_DIR=str(Path.home()/'.jaeger/caller_tokens'),
                      JAEGER_LIFECYCLE_LEASE=str(Path.home()/'.jaeger/control/lifecycle-lease.json'),
                      JAEGER_GLOBAL_STOP_PATH=str(Path.home()/'.jaeger/control/global-stop.json'),
                      JAEGER_WEBUI_UI_DIST=str(ui_dist.resolve()))
    for key in list(os.environ):
        if key.endswith(('_API_KEY','_AUTH_TOKEN','_ACCESS_TOKEN')): os.environ.pop(key,None)
    allowed = set()
    original = socket.socket.connect
    def connect(sock,address):
        if isinstance(address,tuple) and address[:2] in allowed: return original(sock,address)
        raise OSError('Fixture outbound networking disabled')
    socket.socket.connect = connect
    original_ex = socket.socket.connect_ex
    def connect_ex(sock, address):
        if isinstance(address, tuple) and address[:2] in allowed: return original_ex(sock,address)
        raise OSError('Fixture outbound networking disabled')
    socket.socket.connect_ex = connect_ex
    from aiohttp import web
    from jaeger_agent.adapters.openai import OpenAIAdapter
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, ModelConfig, dump_yaml

    def response(self, formatted, interrupt_event, **kwargs):
        messages = formatted.get('messages',[])
        users = [i for i,m in enumerate(messages) if m.get('role')=='user' and 'BLUEPRINT-' in str(m.get('content',''))]
        pos = users[-1] if users else 0
        request = str(messages[pos].get('content','')) if messages else ''
        request = request.rsplit('Current request — act on this and nothing else:\n',1)[-1]
        tools = [m for m in messages[pos+1:] if m.get('role')=='tool']
        if 'BLUEPRINT-SLOW' in request:
            answer = ''
            delta = kwargs.get('on_delta')
            for i in range(20):
                if interrupt_event.wait(.2): break
                chunk = f'SLOW-{i} '
                answer += chunk
                if callable(delta): delta(chunk)
            return {'choices':[{'message':{'role':'assistant','content':answer,'tool_calls':[]},'finish_reason':'stop'}]}
        with (state/'model-calls.jsonl').open('a') as out: out.write(json.dumps({'has_tool_result':bool(tools)})+'\n')
        if not tools and 'BLUEPRINT-WRITE-' in request:
            name='write_file';path='workspace/'+('allowed.txt' if 'BLUEPRINT-WRITE-ALLOW' in request else 'denied.txt')
            args={'path':path,'content':'BLUEPRINT-VERIFIED-BYTES'}
        elif not tools and 'BLUEPRINT-PROCESS' in request:
            import shlex
            code="import os,time;from pathlib import Path;Path('workspace/owned-process.pid').write_text(str(os.getpid()));time.sleep(45)"
            name='terminal';args={'command':shlex.quote(sys.executable)+' -c '+shlex.quote(code),'timeout_s':50}
        else:
            text='BLUEPRINT-TOOL-RETURN' if tools else 'BLUEPRINT-ANSWER'
            delta=kwargs.get('on_delta')
            if callable(delta): delta(text)
            return {'choices':[{'message':{'role':'assistant','content':text,'tool_calls':[]},'finish_reason':'stop'}]}
        return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'fixture-call','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}]}
    OpenAIAdapter.call=response
    layout=InstanceLayout(root=Path(os.environ['JAEGER_INSTANCE_DIR']));layout.ensure_dirs()
    dump_yaml(layout.config_path,Config(instance_name='blueprint',model=ModelConfig(model_path='/dev/null'),external_model=ExternalModelConfig(enabled=True,provider='lmstudio',model='owned-blueprint-model',base_url='http://127.0.0.1:9/v1',api_key_env='',api_key_credential='')))
    gateway=JaegerGatewayApp(store=GatewaySessionStore(state/'gateway_sessions.sqlite3'))
    # Seed canonical store data, never a mock UI or uncertain executed effect.
    gateway.store.ensure_session('agent-native:builder', metadata={'agent_id':'native:builder','home':True})
    for i in range(1,131):
        gateway.store.append_message('agent-native:builder','user',f'BLUEPRINT-HISTORY-{i:03d}')
    gateway.store.ensure_session('agent-native:researcher', metadata={'agent_id':'native:researcher','home':True})
    gateway.store.admit_request('agent-native:researcher','BLUEPRINT-UNKNOWN-DO-NOT-REPLAY',request_id='blueprint-seeded-unknown')
    gateway.store.mark_request_status('blueprint-seeded-unknown','execution_unknown')
    runner=web.AppRunner(gateway.app);await runner.setup()
    await web.TCPSite(runner,'127.0.0.1',0).start();port=runner.addresses[0][1];allowed.add(('127.0.0.1',port))
    os.environ.update(JAEGER_GATEWAY_URL=f'http://127.0.0.1:{port}',JAEGER_GATEWAY_PORT=str(port))
    sys.path.insert(0,str(repo/'jaeger_ai/features/webui'))
    from server import Handler,QuietHTTPServer
    server=QuietHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    (state/'listener.json').write_text(json.dumps({'pid':os.getpid(),'gateway_port':port,'webui_port':server.server_port,'state':str(state),'dist':str(ui_dist.resolve()),'source_sha256':source_sha}))
    print(f'Owned fixture ready: http://127.0.0.1:{server.server_port}/?host=web',flush=True)
    try: await asyncio.Event().wait()
    finally:
        await asyncio.to_thread(server.shutdown);server.server_close();await runner.cleanup()

if __name__=='__main__': asyncio.run(main(Path(sys.argv[1]),Path(sys.argv[2])))
