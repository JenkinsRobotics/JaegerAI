"""Owned Gateway process for contract tests; only the model call is scripted."""

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
        webui = QuietHTTPServer(("127.0.0.1", 0), Handler)
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
