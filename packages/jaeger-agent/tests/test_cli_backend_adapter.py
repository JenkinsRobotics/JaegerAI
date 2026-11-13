"""CliBackendAdapter — flatten, parse, no live CLI."""

from __future__ import annotations

import json
from types import SimpleNamespace

from jaeger_agent.adapters.cli_backend import (
    CliBackendAdapter,
    flatten_messages,
    parse_cli_text,
)
from jaeger_agent.schemas.message_types import Message
from jaeger_os.core.tools.tool_schema import ToolDef


def test_flatten_messages_joins_system_and_transcript():
    prompt = flatten_messages(
        [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="user", content="status?"),
        ],
        [],
        "you are jaeger",
    )
    assert "System:\nyou are jaeger" in prompt
    assert "User:\nhi" in prompt
    assert "Assistant:\nhello" in prompt
    assert "User:\nstatus?" in prompt


def test_flatten_mentions_jaeger_tools():
    from pydantic import BaseModel

    class _Args(BaseModel):
        pass

    tool = ToolDef(
        name="get_time",
        description="now",
        args_model=_Args,
        fn=lambda: "ok",
    )
    prompt = flatten_messages(
        [Message(role="user", content="what time")],
        [tool],
        "",
    )
    assert "get_time" in prompt
    assert "Jaeger owns tools" in prompt


def test_parse_json_stdout_extracts_result():
    raw = json.dumps({"type": "result", "result": "the sky is blue"})
    adapter = CliBackendAdapter("claude", executable="/bin/true")
    msg = adapter.parse_response({"stdout": raw, "stderr": "", "returncode": 0})
    assert msg["role"] == "assistant"
    assert msg["content"] == "the sky is blue"


def test_parse_nested_content_and_ndjson():
    blob = (
        json.dumps({"type": "item", "text": "ignored"})
        + "\n"
        + json.dumps({"message": {"content": "final answer"}})
        + "\n"
    )
    assert parse_cli_text(blob) == "final answer"


def test_parse_falls_back_to_raw_stdout():
    adapter = CliBackendAdapter("hermes", executable="/bin/true")
    msg = adapter.parse_response({"stdout": "plain text reply\n", "stderr": ""})
    assert msg["content"] == "plain text reply"


def test_format_messages_returns_prompt_payload():
    adapter = CliBackendAdapter("codex", executable="/bin/true")
    formatted = adapter.format_messages(
        [Message(role="user", content="ping")],
        [],
        "sys",
    )
    assert formatted["prompt"].startswith("System:\nsys")
    assert "User:\nping" in formatted["prompt"]


def test_health_check_missing_binary(monkeypatch):
    adapter = CliBackendAdapter("claude")

    def boom(_backend_id):
        raise RuntimeError("CLI backend 'claude' is not installed on PATH")

    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.get_spec",
        boom,
    )
    result = adapter.health_check()
    assert result["ok"] is False
    assert "not installed" in result["detail"]


def test_spawn_uses_argv_and_env_allowlist(monkeypatch):
    """No shell, no leaked env. Stdin backends pass the prompt as bytes."""
    adapter = CliBackendAdapter("claude", executable="/opt/homebrew/bin/claude")
    spec = SimpleNamespace(
        args=("--print", "--output-format", "json"),
        prompt_mode="stdin",
        credential_env=("ANTHROPIC_API_KEY",),
        probe_args=("--version",),
        executables=("claude",),
        id="claude",
    )
    captured: dict = {}

    class _Proc:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.returncode = 0
            self.pid = 4242

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            captured["timeout"] = timeout
            return b'{"result": "ok"}', b""

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(
        "jaeger_agent.adapters.cli_backend.subprocess.Popen", _Proc,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-leak")
    raw = adapter._spawn(
        ["/opt/homebrew/bin/claude", "--print", "--output-format", "json"],
        b"hello",
        spec,
    )
    assert captured["shell"] is False
    assert captured["args"][0] == "/opt/homebrew/bin/claude"
    assert captured["input"] == b"hello"
    env = captured["env"]
    assert env["ANTHROPIC_API_KEY"] == "sk-secret"
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert json.loads(raw["stdout"])["result"] == "ok"


def test_grok_stream_delivers_before_exit_and_never_replays_final(tmp_path):
    import sys
    import threading
    script = tmp_path / "provider.py"
    script.write_text("""import json,time,sys
print(json.dumps({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':'Hello '}}}),flush=True)
sys.stderr.write('x'*100000);sys.stderr.flush()
time.sleep(.15)
print(json.dumps({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':'world'}}}),flush=True)
print(json.dumps({'type':'result','result':'Hello world'}),flush=True)
""")
    adapter = CliBackendAdapter('grok', executable=sys.executable, spec=SimpleNamespace(args=(str(script),'--output-format','json'),prompt_mode='placeholder'), timeout_s=3)
    chunks=[]
    def delta(text):
        chunks.append(text)
        assert adapter._proc.poll() is None
    raw=adapter.call({'prompt':'hello'}, threading.Event(), on_delta=delta)
    assert chunks==['Hello ', 'world']
    assert adapter.parse_response(raw)['content']=='Hello world'
    assert len(raw['stderr'])==100000
    assert adapter.supports('streaming')


def test_stream_ignores_reasoning_final_and_nested_agent_output():
    from jaeger_agent.adapters.cli_stream import text_delta
    assert text_delta(b'{"type":"result","result":"final"}')==''
    assert text_delta(b'{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"private"}}}')==''
    assert text_delta(b'{"type":"stream_event","parent_tool_use_id":"child","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"nested"}}}')==''
    assert text_delta(b'not json')==''


def test_stream_timeout_stops_owned_process(tmp_path):
    import sys, threading, pytest
    script=tmp_path/'provider.py';script.write_text('import time; time.sleep(10)')
    adapter=CliBackendAdapter('grok',executable=sys.executable,spec=SimpleNamespace(args=(str(script),),prompt_mode='placeholder'),timeout_s=.1)
    with pytest.raises(TimeoutError):
        adapter.call({},threading.Event(),on_delta=lambda _:None)
    assert adapter._proc.poll() is not None


def test_cli_failure_is_not_saved_as_an_assistant_answer(tmp_path):
    import sys, threading, pytest
    script=tmp_path/'provider.py';script.write_text('import sys;sys.stderr.write("provider failed");sys.exit(7)')
    adapter=CliBackendAdapter('grok',executable=sys.executable,spec=SimpleNamespace(args=(str(script),),prompt_mode='placeholder'))
    with pytest.raises(RuntimeError,match='status 7'):
        adapter.call({},threading.Event(),on_delta=lambda _:None)


def test_stream_filters_split_tool_envelopes_without_dropping_prose():
    from jaeger_agent.adapters.cli_stream import VisibleTextStream
    chunks=[];stream=VisibleTextStream(chunks.append)
    for text in ['Checking. <to','ol_call>{"name":"get_time",','"arguments":{}}</tool_','call>Done.']:
        stream.feed(text)
    stream.finish()
    assert ''.join(chunks)=='Checking. Done.'


def test_tool_schemas_survive_cli_formatting_and_use_existing_repair():
    from pydantic import BaseModel
    from jaeger_agent.parsing.tool_call_repair import repair_plain_text_tool_calls
    class Args(BaseModel):
        path: str
    tool=ToolDef(name='read_file',description='Read one file',args_model=Args,fn=lambda **_:None)
    prompt=flatten_messages([Message(role='user',content='Read the file')],[tool],'')
    assert '"required": ["path"]' in prompt
    assert '<tool_call>' in prompt
    calls,text=repair_plain_text_tool_calls('<tool_call>{"name":"read_file","arguments":{"path":"README.md"}}</tool_call>',allowed_tool_names={'read_file'})
    assert calls[0]['function']['name']=='read_file'
    assert json.loads(calls[0]['function']['arguments'])=={'path':'README.md'}
    assert not text.strip()


def test_repaired_cli_call_reaches_existing_dispatch_and_approval_hook():
    import threading
    from pydantic import BaseModel
    from jaeger_agent.loop.jaeger_agent import JaegerAgent
    from jaeger_agent.loop.callbacks import AgentCallbacks
    class Args(BaseModel):
        label: str
    executed=[];approvals=[]
    class Scripted(CliBackendAdapter):
        def __init__(self):
            super().__init__('grok', executable='/bin/true');self.round=0
        def call(self, formatted, interrupt_event: threading.Event, **kwargs):
            self.round+=1
            return {'stdout':json.dumps({'result':'<tool_call>{"name":"read_fixture","arguments":{"label":"proof"}}</tool_call>' if self.round==1 else 'Done'}),'returncode':0}
    tool=ToolDef(name='read_fixture',description='Read fixture',args_model=Args,fn=lambda label:executed.append(label) or 'value',side_effect='read')
    agent=JaegerAgent(Scripted(),tools=[tool],callbacks=AgentCallbacks(before_tool_call=lambda name,args:approvals.append((name,args))),tool_visibility=False,turn_start_hook=False)
    assert agent.run_turn('Read fixture')=='Done'
    assert approvals==[('read_fixture',{'label':'proof'})]
    assert executed==['proof']


def test_grok_without_delta_sink_still_reports_progress(tmp_path):
    """Root cause of the 120s StaleCallTimeout: a grok call with no on_delta
    used communicate(), so the stale detector saw zero progress and measured
    wall-clock time. Grok now always streams so liveness is observable."""
    import sys, threading
    script = tmp_path / 'provider.py'
    script.write_text("""import json,time
for i in range(4):
    print(json.dumps({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'.'}}}),flush=True)
    time.sleep(.2)
print(json.dumps({'type':'result','result':'done'}),flush=True)
""")
    adapter = CliBackendAdapter('grok', executable=sys.executable, spec=SimpleNamespace(args=(str(script),), prompt_mode='placeholder'), timeout_s=10)
    raw = adapter.call({'prompt': 'x'}, threading.Event(), stale_timeout=0.5)
    assert adapter.parse_response(raw)['content'] == 'done'


def test_first_progress_limit_never_below_cli_floor():
    from jaeger_agent.adapters.cli_backend import CLI_FIRST_PROGRESS_FLOOR_S, _first_progress_limit
    assert _first_progress_limit(None, 120.0, True) == CLI_FIRST_PROGRESS_FLOOR_S
    assert _first_progress_limit(900.0, 120.0, True) == 900.0
    assert _first_progress_limit(None, None, True) is None
    assert _first_progress_limit(60.0, 120.0, False) is None
