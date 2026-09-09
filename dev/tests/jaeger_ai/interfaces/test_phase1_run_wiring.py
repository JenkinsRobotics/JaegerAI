import base64
import io
import json
import queue
from types import SimpleNamespace

import pytest

from jaeger_ai.interfaces import bridge
from jaeger_ai.core.runtime.native_turns import NativeTurns
from jaeger_ai.interfaces.hermes_profile_adapters.run_input import normalize_input, attachment_prompt
from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import RunsHTTP


def test_structured_text_and_private_attachment_bytes(tmp_path):
    data = b'attachment contents'
    text, files = normalize_input([{'role':'user','content':[
        {'type':'text','text':'Read this'},
        {'type':'input_file','file_data':'data:text/plain;base64,'+base64.b64encode(data).decode()},
    ]}])
    prompt = attachment_prompt(tmp_path,'a'*32,text,files)
    path = tmp_path/'attachments'/('a'*32)/'0.txt'
    assert path.read_bytes() == data
    assert path.stat().st_mode & 0o777 == 0o600
    assert str(path) in prompt and 'Read this' in prompt
    assert 'data:text/plain' not in prompt


@pytest.mark.parametrize('body', [[{'type':'audio','data':'x'}], [{'type':'text','text':42}], [{'type':'image_url','image_url':{'url':'data:image/png;base64,!!!!'}}]])
def test_invalid_blocks_are_explicit_errors(body):
    with pytest.raises(ValueError): normalize_input(body)


def test_http_preserves_model_provider_and_structured_input():
    calls=[]
    service=SimpleNamespace(start=lambda *a,**k:calls.append((a,k)))
    handler=SimpleNamespace(headers={},native_runs=lambda:service)
    content=[{'type':'text','text':'hello'}]
    RunsHTTP.create_native_run(handler,{'session_id':'s','input':content,'model':'picked','provider':'ollama'})
    assert calls == [(('s',content,None),{'model':'picked','provider':'ollama'})]


def test_queued_cancel_is_durable_and_tombstone_cannot_execute(tmp_path, monkeypatch):
    ctx=bridge._Ctx()
    ctx.layout=SimpleNamespace(run_dir=tmp_path)
    output=io.StringIO()
    turn='f'*32
    request={'turn_id':turn,'session':'test-session','text':'/do-not-run','_out':output,'_native_accepted':True}
    NativeTurns(tmp_path).accept(turn,'test-session')
    ctx.turn_controls[turn]='queued'
    ctx.queued_requests[turn]=request
    assert bridge._cancel_queued_turn(ctx,turn)
    assert not bridge._cancel_queued_turn(ctx,turn)
    assert NativeTurns(tmp_path).get(turn,'test-session')['status']=='cancelled'
    q=queue.Queue();q.put(request);q.put(None)
    monkeypatch.setattr(bridge,'_request_text',lambda _:pytest.fail('Cancelled request reached dispatch'))
    bridge._turn_worker(io.StringIO(),ctx,q)
    assert json.loads(output.getvalue())['cancelled'] is True
    assert not ctx.turn_controls and not ctx.queued_requests


def test_active_run_cannot_be_falsely_cancelled_as_queued(tmp_path):
    ctx=bridge._Ctx();ctx.layout=SimpleNamespace(run_dir=tmp_path)
    ctx.turn_controls['a'*32]='active'
    assert not bridge._cancel_queued_turn(ctx,'a'*32)
    assert ctx.turn_controls['a'*32]=='active'
