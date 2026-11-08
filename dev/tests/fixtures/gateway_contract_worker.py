"""Owned Gateway with synthetic provider and nominated lifecycle/crash controls."""

import asyncio
import json
import os
import socket
import sys
import threading
from pathlib import Path


async def main(state: Path, *, serve_webui: bool = False) -> None:
    # Set before any product imports. Never read the operator's credentials or
    # attach to an existing bridge. Every output belongs to this test process.
    os.environ.update({
        "JAEGER_STATE_DIR": str(state),
        "JAEGER_STATE_HOME": str(state),
        "JAEGER_HOME": str(state),
        "JAEGER_INSTANCE_DIR": str(state / "instances" / "contract"),
        "HERMES_HOME": str(state / "hermes"),
        "HERMES_WEBUI_STATE_DIR": str(state / "webui"),
        "HERMES_WEBUI_DEFAULT_WORKSPACE": str(state / "workspace"),
        "JAEGER_NO_ATTACH": "1",
        "JAEGER_NO_GUI": "1",
        "JAEGER_RUNTIME_MODE": "owner",
        "JAEGER_CONTRACT_API_KEY": "synthetic-contract-key",
        "HERMES_WEBUI_PASSWORD": "synthetic-contract-password",
    })

    # The child serves an owned listener but must never initiate a connection
    # to an operator daemon or an external provider, including optional probes.
    allowed_connections = set()

    def guarded_connect(original):
        def connect(sock, address):
            if isinstance(address, tuple) and address[:2] in allowed_connections:
                return original(sock, address)
            raise OSError("outbound networking disabled in contract worker")
        return connect

    socket.socket.connect = guarded_connect(socket.socket.connect)
    socket.socket.connect_ex = guarded_connect(socket.socket.connect_ex)

    from aiohttp import web
    from jaeger_agent.adapters.openai import OpenAIAdapter

    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import (
        Config,
        ExternalModelConfig,
        ModelConfig,
        dump_yaml,
    )

    # Test-local process-loss barrier. No production environment switch or
    # endpoint exists. The parent kills only this fixture's recorded child.
    fault = json.loads(os.environ.get("JAEGER_CONTRACT_RECEIPT_FAULT", "null"))
    if fault is not None and fault.get('background'):
        def barrier(request_id):
            (state / 'receipt-fault-ready.json').write_text(json.dumps({
                **fault, 'request_id': request_id, 'pid': os.getpid()}))
            threading.Event().wait()

        if fault.get('rotate'):
            # A synthetic executor closes its first normally returned slice.
            # The next real TurnExecutive call must create/bind a distinct root;
            # no task completion or final receipt is fabricated here.
            original_react = EntityRuntime.run_subordinate_react
            def rotated_react(self, prompt, **kwargs):
                captured = []
                callback = kwargs.get('on_run')
                def accept(ident):
                    captured.append(ident)
                    if callback:
                        callback(ident)
                kwargs['on_run'] = accept
                result = original_react(self, prompt, **kwargs)
                marker = state / 'rotation-returned.json'
                if captured and not marker.exists() and str(kwargs.get('session_key', '')).startswith('task:'):
                    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
                    assert not result.get('halt_reason') and not result.get('error')
                    SqliteRunStore().transition(captured[-1], 'completed', reason='synthetic_returned_slice')
                    marker.write_text(json.dumps({'native_run_id': captured[-1]}))
                return result
            EntityRuntime.run_subordinate_react = rotated_react
        if fault['phase'] == 'native_settled':
            from jaeger_ai.core.tasks import background_receipts
            original_settle = background_receipts.complete_native_runs
            def fault_settle(owner, task, runs):
                result = original_settle(owner, task, runs)
                barrier(f'{task.task_id}:{task.payload.get("attempt", 0)}')
                return result
            background_receipts.complete_native_runs = fault_settle
        elif fault['phase'] == 'before_seal' and hasattr(JaegerGatewayApp, '_commit_background_outcome'):
            original_background = JaegerGatewayApp._commit_background_outcome
            def fault_background(self, request_id, *args, **kwargs):
                barrier(request_id)
            JaegerGatewayApp._commit_background_outcome = fault_background
        else:
            # The same final-projection boundary exists on the unfixed baseline.
            # Only the fixed producer has committed a background seal by here.
            original_terminal = JaegerGatewayApp._persist_terminal
            def fault_terminal(self, request_id, session_id, status, result, **kwargs):
                if session_id.startswith('task:') and status == 'completed' and not result.get('halt_reason'):
                    barrier(request_id)
                return original_terminal(self, request_id, session_id, status, result, **kwargs)
            JaegerGatewayApp._persist_terminal = fault_terminal
    elif fault is not None:
        original_commit = JaegerGatewayApp._commit_owner_outcome

        def fault_commit(self, request_id, *args, **kwargs):
            row = self.store.get_request(request_id)
            nominated = (request_id == fault["request_id"]
                         and row["session_id"] == fault["session_id"])
            if not nominated:
                return original_commit(self, request_id, *args, **kwargs)
            if fault["phase"] == "after_seal":
                original_commit(self, request_id, *args, **kwargs)
            else:
                assert fault["phase"] == "before_seal"
            # _commit_owner_outcome returns only AFTER the shared SQLite
            # transaction has committed. Parent independently reads proof.
            (state / "receipt-fault-ready.json").write_text(json.dumps({
                **fault, "pid": os.getpid(),
            }))
            threading.Event().wait()  # Only parent SIGKILL releases this child.

        JaegerGatewayApp._commit_owner_outcome = fault_commit

    if os.environ.get("JAEGER_CONTRACT_RESEARCH") == "1":
        from dev.tests.fixtures.research_contract import install_retrieval
        install_retrieval()

    def current_request(messages):
        """The request this call serves: the last user message, minus the
        other-session context EntityRuntime prefixes above its "Current
        request" marker. Triggers must not fire on another session's turn."""
        users = [m for m in messages if m.get("role") == "user"]
        text = str(users[-1].get("content", "")) if users else ""
        return text.rsplit("Current request — act on this and nothing else:\n", 1)[-1]

    def model_response(self, formatted, interrupt_event, **kwargs):
        with (state / "provider-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"model": self.model}) + "\n")
        messages = formatted.get("messages", [])
        request = current_request(messages)
        from jaeger_agent.task_port import current_task_context
        with (state / "provider-requests.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"request": request,
                "request_id": (current_task_context() or {}).get("request_id")}) + "\n")
        if any('CONTRACT-BACKGROUND-YIELD' in str(m.get('content', ''))
               for m in messages if m.get('role') == 'user'):
            # Real durable owner yields at its normal budget; only the provider is scripted.
            done = [m for m in messages if m.get('tool_call_id') == 'yield-ledger']
            if not done:
                return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[
                    {'id':'yield-ledger','type':'function','function':{'name':'work_ledger',
                        'arguments':json.dumps({'action':'create','task_name':'Yield observation','total_items':1})}}
                ]},'finish_reason':'tool_calls'}]}
            answer = 'Observed checkpoint ' + str(len(messages)) + '; one item remains.'
            return {'choices':[{'message':{'role':'assistant','content':answer,'tool_calls':[]},'finish_reason':'stop'}]}
        if "CONTRACT-RESEARCH" in request:
            assert os.environ.get("JAEGER_CONTRACT_RESEARCH") == "1"
            from dev.tests.fixtures.research_contract import model_response as research_response
            return research_response(messages)
        if "CONTRACT-QUEUE-DEFAULT" in request:
            responses = [m for m in messages if m.get('tool_call_id') == 'queue-default']
            if not responses:
                return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[
                    {'id':'queue-default','type':'function','function':{
                        'name':'queue_background_task','arguments':json.dumps({
                            'description':'CONTRACT-DURABLE: produce and verify the report'})}}
                ]},'finish_reason':'tool_calls'}]}
            assert any('task_id' in str(m.get('content','')) for m in responses), 'Task submission failed'
            return {'choices':[{'message':{'role':'assistant','content':'Background report queued',
                'tool_calls':[]},'finish_reason':'stop'}]}
        if "CONTRACT-CLARIFY" in request:
            # Wire tool messages carry tool_call_id, not name (OpenAI chat
            # format, openai.py format_messages). Match the result by the id
            # the clarify call was issued with, not by a name field the wire
            # format does not have.
            answers = [m for m in messages if m.get("role") == "tool" and m.get("tool_call_id") == "contract-clarify"]
            if not answers:
                return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "contract-clarify", "type": "function", "function": {
                        "name": "clarify", "arguments": json.dumps({"question": "Which environment should be used?"}),
                    },
                }]}, "finish_reason": "tool_calls"}]}
            return {"choices": [{"message": {"role": "assistant", "content": "CLARIFICATION-ANSWER-RECEIVED", "tool_calls": []}, "finish_reason": "stop"}]}
        if any('CONTRACT-FOREGROUND-RESUME' in str(m.get('content', ''))
               for m in messages if m.get('role') == 'user'):
            from jaeger_agent.task_port import current_task_context
            context = current_task_context() or {}
            background = bool((context.get('execution', {}).get('options') or {}).get('background'))
            if os.environ.get('JAEGER_REVIEW_BACKGROUND_SLICES') == '1':
                background = not str(context.get('request_id', '')).endswith(':0')
            with (state / 'foreground-resume-calls.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'request_id': context.get('request_id'),
                                         'background': background}) + '\n')
            tool_messages = [m for m in messages if m.get('role') == 'tool']
            prefix = 'foreground-resume-final-' if background else 'foreground-resume-first-'
            if background:
                assert any(m.get('tool_call_id') == 'foreground-resume-first-2' and
                           'FOREGROUND-PARTIAL' in str(m.get('content', ''))
                           for m in tool_messages), 'Original native trajectory was not restored'
                steps = [
                    ('write_file', {'path':'workspace/foreground-report.txt', 'content':'FOREGROUND-FINAL-VERIFIED'}),
                    ('read_file', {'path':'workspace/foreground-report.txt'}),
                    ('work_ledger', {'action':'update', 'completed_ids':['report'], 'remaining_count':0}),
                    ('complete_task', {'summary':'Foreground task resumed and verified',
                        'evidence':'Read back workspace/foreground-report.txt: FOREGROUND-FINAL-VERIFIED'}),
                ]
            else:
                steps = [
                    ('work_ledger', {'action':'create', 'task_name':'Foreground report', 'total_items':1,
                        'verify':{'kind':'paths_exist','paths':['workspace/foreground-report.txt']}}),
                    ('write_file', {'path':'workspace/foreground-report.txt', 'content':'FOREGROUND-PARTIAL'}),
                    ('read_file', {'path':'workspace/foreground-report.txt'}),
                ]
            step = len([m for m in tool_messages if str(m.get('tool_call_id') or '').startswith(prefix)])
            if step < len(steps):
                name, args = steps[step]
                if name == 'complete_task':
                    assert any(m.get('tool_call_id') == 'foreground-resume-final-1' and
                               'FOREGROUND-FINAL-VERIFIED' in str(m.get('content', ''))
                               for m in tool_messages), 'Final report readback failed'
                return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[
                    {'id':prefix+str(step),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
                ]},'finish_reason':'tool_calls'}]}
            answer = 'Foreground task resumed and verified' if background else 'FOREGROUND-PARTIAL checkpoint retained; work remains.'
            return {'choices':[{'message':{'role':'assistant','content':answer,'tool_calls':[]},'finish_reason':'stop'}]}
        if 'CONTRACT-DURABLE' in request or 'CONTRACT-QUEUE-BARE' in request:
            if fault and fault.get('rotate') and not (state / 'rotation-returned.json').exists():
                return {'choices':[{'message':{'role':'assistant','content':'Initial synthesis returned; report remains to be written.', 'tool_calls':[]}, 'finish_reason':'stop'}]}
            # Script only the provider boundary; ledger, file tool, Gateway,
            # approvals, checkpoints and result delivery are production code.
            path = 'queue-bare-report.txt' if 'CONTRACT-QUEUE-BARE' in request else 'workspace/durable-report.txt'
            tool_messages = [m for m in messages if m.get('role') == 'tool']
            steps = [
                ('work_ledger', {'action':'create', 'task_name':'Durable report', 'total_items':1,
                                 'verify':{'kind':'paths_exist', 'paths':[path]}}),
                ('write_file', {'path':path, 'content':'DURABLE-VERIFIED-CONTENT'}),
                ('read_file', {'path':path}),
                ('work_ledger', {'action':'update', 'completed_ids':['report'], 'remaining_count':0}),
                ('complete_task', {'summary':'Durable report verified',
                    'evidence':f'Wrote and read back {path}: DURABLE-VERIFIED-CONTENT'}),
            ]
            step = len(tool_messages)
            if step < len(steps):
                name, args = steps[step]
                if name == 'complete_task':
                    assert any(m.get('tool_call_id') == 'durable-2' and
                               'DURABLE-VERIFIED-CONTENT' in str(m.get('content', ''))
                               for m in tool_messages), 'Durable report readback failed'
                return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[
                    {'id':f'durable-{step}', 'type':'function', 'function':{'name':name,'arguments':json.dumps(args)}}
                ]},'finish_reason':'tool_calls'}]}
            return {'choices':[{'message':{'role':'assistant','content':'Durable report verified', 'tool_calls':[]},'finish_reason':'stop'}]}
        if "CONTRACT-ERROR" in request or "SIMULATE-ERROR" in request:
            raise RuntimeError("Deliberate simulated backend provider error")
        if "CONTRACT-LONG" in request or "LONG-CONTENT" in request:
            import time
            long_content = (
                "# Comprehensive Jaeger Diagnostics Report\n\n"
                "## Overview\n"
                "Testing multiline rendering, Unicode \U0001f680, formatting, and scroll mechanics.\n\n"
                "### Feature Matrix\n"
                "- **Status**: Active and verified \u2728\n"
                "- **Security Tier**: Enforced across all boundaries \U0001f6e1\ufe0f\n"
                "- **Link**: [JaegerAI Repository](https://github.com/JenkinsRobotics/JaegerAI)\n\n"
                "### Diagnostic Source\n"
                "```python\n"
                "def evaluate_runtime_matrix():\n"
                "    results = []\n"
                "    for step in range(1, 35):\n"
                "        results.append({\n"
                "            'step': step,\n"
                "            'status': 'passed',\n"
                "            'latency_ms': step * 12,\n"
                "            'signature': f'probe_{step:03d}',\n"
                "        })\n"
                "    return results\n"
                "\n"
                "report = evaluate_runtime_matrix()\n"
                "print(f'Processed {len(report)} execution boundaries.')\n"
                "```\n\n"
                "### Summary Table\n"
                "| Boundary | Mode | Health |\n"
                "| :--- | :--- | :--- |\n"
                "| Gateway | Daemon | Normal |\n"
                "| WebUI | Loopback | Online |\n"
                "| Bridge | IPC | Connected |\n\n"
                "Final line: End of long-form diagnostic response."
            )
            on_delta = kwargs.get("on_delta")
            if callable(on_delta):
                for i in range(0, len(long_content), 40):
                    on_delta(long_content[i:i+40])
                    time.sleep(0.02)
            return {"choices": [{"message": {
                "role": "assistant", "content": long_content, "tool_calls": [],
            }, "finish_reason": "stop"}]}
        if "CONTRACT-WAIT" in request or "SLOW-STREAM" in request:
            # Deterministic in-flight provider boundary for cancellation tests.
            # Parent owns this release file and always kills its own child.
            (state / "provider-waiting").touch()
            on_delta = kwargs.get("on_delta")
            counter = 0
            while not (state / "provider-release").exists():
                if interrupt_event.wait(0.1):
                    from jaeger_agent.loop.interrupt import AgentInterrupted
                    raise AgentInterrupted("contract provider interrupted")
                counter += 1
                if callable(on_delta):
                    on_delta(f"Streaming token chunk {counter}... ")
                if counter > 60:
                    break
            return {"choices": [{"message": {
                "role": "assistant", "content": f"Completed after {counter} chunks", "tool_calls": [],
            }, "finish_reason": "stop"}]}
        if "CONTRACT-STALL" in request and "SYSTEM NUDGE" not in request:
            stall = "Let me start by reading the notes and I'll process everything."
            on_delta = kwargs.get("on_delta")
            if callable(on_delta):
                on_delta(stall)
            return {"choices": [{"message": {
                "role": "assistant", "content": stall, "tool_calls": [],
            }, "finish_reason": "stop"}]}
        if ("CONTRACT-WRITE" in request
                and not any(message.get("role") == "tool" for message in messages)):
            return {"choices": [{"message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "contract-write", "type": "function", "function": {
                        "name": "write_file", "arguments": json.dumps({
                            "path": "workspace/contract-output.txt", "content": "CONTRACT-CONTENT",
                        }),
                    },
                }],
            }, "finish_reason": "tool_calls"}]}
        # Stream like a real streaming adapter when the loop asks for it.
        if request.strip().startswith("Say "):
            ans = request.strip()[4:].strip()
        elif "Say CONTRACT-ANSWER" in request:
            ans = "CONTRACT-ANSWER"
        else:
            ans = f"CONTRACT-ANSWER: Received message: {request[:50].strip()}"
        on_delta = kwargs.get("on_delta")
        if callable(on_delta):
            for chunk in (ans[:15], ans[15:30], ans[30:]):
                if chunk:
                    on_delta(chunk)
        return {"choices": [{"message": {
            "role": "assistant", "content": ans, "tool_calls": [],
        }, "finish_reason": "stop"}]}

    OpenAIAdapter.call = model_response
    layout = InstanceLayout(root=Path(os.environ["JAEGER_INSTANCE_DIR"]))
    layout.ensure_dirs()
    if not layout.config_path.exists():
        dump_yaml(layout.config_path, Config(
            instance_name="contract", model=ModelConfig(model_path="/dev/null"),
            external_model=ExternalModelConfig(
                enabled=True, provider="openai", model="contract-model",
                base_url="http://127.0.0.1:9/v1", api_key_env="JAEGER_CONTRACT_API_KEY",
            ),
        ))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(state / "gateway_sessions.sqlite3"))
    runner = web.AppRunner(gateway.app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    gateway_port = runner.addresses[0][1]
    webui = None
    if serve_webui:
        allowed_connections.add(("127.0.0.1", gateway_port))
        os.environ["JAEGER_GATEWAY_URL"] = f"http://127.0.0.1:{gateway_port}"
        os.environ["JAEGER_GATEWAY_PORT"] = str(gateway_port)
        webui_root = Path(__file__).resolve().parents[3] / "jaeger_ai/features/webui"
        sys.path.insert(0, str(webui_root))
        from server import Handler, QuietHTTPServer

        # Real handlers and authentication, without production launcher's
        # optional model warmups, service management or package installation.
        webui = QuietHTTPServer(("127.0.0.1", int(os.environ.get("JAEGER_CONTRACT_WEBUI_PORT", "0"))), Handler)
        threading.Thread(target=webui.serve_forever, daemon=True).start()
    runtime = EntityRuntime.get_singleton()
    ready = state / "listener.tmp"
    ready.write_text(json.dumps({
        "pid": os.getpid(), "port": gateway_port,
        "webui_port": webui.server_port if webui is not None else None,
        "entity_id": runtime.identity.entity_id,
        "mode": runtime.mode.value, "resident": runtime.is_resident,
    }), encoding="utf-8")
    ready.replace(state / "listener.json")
    try:
        await asyncio.Event().wait()
    finally:
        if webui is not None:
            await asyncio.to_thread(webui.shutdown)
            webui.server_close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve(), serve_webui="--webui" in sys.argv[2:]))
