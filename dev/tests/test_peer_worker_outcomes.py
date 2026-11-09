"""Known worker outcomes survive the real MCP message producer and durable outbox.

Only execution and transport are synthetic. No engine, provider, or credential
is contacted. Delivery failure retains the same id/payload, not another job.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.agent_bridge import engine_worker, rackpc_worker, mcp
from jaeger_ai.features.agent_bridge.service import AgentMessages


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None):
        def register(fn):
            self.tools[name or fn.__name__] = fn
            return fn
        return register


@pytest.mark.parametrize("worker", ["hermes", "openclaw", "rackpc"])
@pytest.mark.parametrize("outcome", ["done", "failed", "timeout", "error", "empty"])
def test_known_outcome_survives_outbox_and_mcp(tmp_path, monkeypatch, worker, outcome):
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    messages = AgentMessages(GatewaySessionStore(tmp_path / "messages.sqlite3"))
    task = messages.send("grokbot", {"id": "work", "thread": "thread", "to": worker,
        "kind": "task", "title": "Synthetic job", "body": "Synthetic job"})
    registry = Registry()
    sent, attempts, runs = [], [], []

    class Client:
        caller = worker

        def _call(self, method, path, body=None):
            assert (method, path) == ("POST", "/v1/agent-messages")
            saved = messages.send(worker, body)
            sent.append(saved)
            return saved

    mcp.register(registry, lambda ctx: Client())

    def deliver(tool, args):
        assert tool == "send_message"
        attempts.append(dict(args))
        if len(attempts) == 1:
            raise OSError("synthetic transport loss before delivery")
        return asyncio.run(registry.tools[tool](**args))

    def execute(*args, **kwargs):
        runs.append(1)
        if outcome == "timeout":
            if worker == "rackpc":
                raise TimeoutError("synthetic timeout")
            raise engine_worker.subprocess.TimeoutExpired("synthetic", 1)
        if outcome == "error":
            raise OSError("synthetic error")
        body = "" if outcome in ("failed", "empty") else "synthetic answer"
        if worker == "rackpc":
            return {"message": {"content": body}}
        stdout = json.dumps({"payloads": [{"text": body}]}) if worker == "openclaw" else body
        return SimpleNamespace(returncode=1 if outcome == "failed" else 0, stdout=stdout)

    if worker == "rackpc":
        w = rackpc_worker
        monkeypatch.setattr(w, "WORKDIR", tmp_path / worker)
        monkeypatch.setattr(w, "_ollama", execute)
        monkeypatch.setattr(w, "call", deliver)
        monkeypatch.setattr(w, "pending", lambda state: [task] if "work" not in state.data["done"] else [])
        state = w.State(tmp_path / "state.json")
        tick = lambda: w.tick(state)
        outbox = w._outbox_path("work")
    else:
        w = engine_worker
        monkeypatch.setattr(w, "workspace", lambda engine: tmp_path / engine)
        monkeypatch.setattr(w, "engine_env", lambda engine: {})
        monkeypatch.setattr(w, "command", lambda *args: ["synthetic-not-executed"])
        monkeypatch.setattr(w.subprocess, "run", execute)
        monkeypatch.setattr(w, "device_ok", lambda: [])
        monkeypatch.setattr(w, "call", lambda engine, tool, args: deliver(tool, args))
        monkeypatch.setattr(w, "pending", lambda engine, state: [task] if "work" not in state["done"] else [])
        state = {"after": 0, "since": 0, "done": []}
        tick = lambda: w.tick(worker, state, tmp_path / "state.json")
        outbox = w.outbox_path(worker, "work")
    assert tick() == 1 and outbox.exists() and not sent
    assert tick() == 0 and not outbox.exists()
    assert tick() == 0
    assert runs == [1] and len(sent) == 1 and attempts[0] == attempts[1]
    result = sent[0]
    assert result["from"] == worker and result["to"] == "grokbot" and result["reply_to"] == "work"
    assert result["status_line"] == ("failed" if outcome == "empty" else outcome)
    assert "verified" not in result and "check" not in result
