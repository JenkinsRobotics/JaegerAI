"""Each framework responsibility reports itself LIVE, over the same SSE stream
the Process view reads — driven by a real turn, not fabricated events.

One real JaegerAgent loop runs through the Gateway's owner path
(``_owner_react_turn``): a primary adapter that fails (fallback), a scripted
fallback that asks for a real registered tool, the real tool executor and
authority boundary, the real memory store, the real delegate wrapper, and the
real terminal persistence. The test then opens
``/v1/sessions/{id}/stream?scope=session`` and asserts each responsibility's
event arrives as an SSE frame.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import BaseModel, Field

from jaeger_agent import JaegerAgent, ProviderAdapter, clear_registry, register_tool
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class _Down(ProviderAdapter):
    name = "down"

    def describe(self):
        return "down-adapter"

    def format_messages(self, messages, tools, system):
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):
        raise RuntimeError("provider unavailable")

    def parse_response(self, raw):
        return raw

    def supports(self, feature):
        return False


class _Scripted(_Down):
    name = "scripted"
    model = "scripted-model"

    def __init__(self, script):
        self.script = list(script)

    def describe(self):
        return "scripted-adapter"

    def call(self, formatted, interrupt_event, **kwargs):
        return self.script.pop(0)


class _Args(BaseModel):
    topic: str = Field(default="x")


@pytest.fixture()
def turn(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    clear_registry()

    @register_tool("look_up_notes", "Look up notes.", _Args, side_effect="read")
    def _look_up_notes(topic: str = "x") -> dict:
        from jaeger_agent.memory import memory
        from jaeger_ai.core.runtime import subagents
        try:  # the real memory store (it may refuse when unbound; the read is still observed)
            memory.recall(topic)
        except Exception:
            pass
        sub = subagents._reported("internal", "helper", topic, lambda: {"delegated": True, "answer": "ok"})
        return {"ok": True, "notes": sub["answer"]}

    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    app = JaegerGatewayApp(store=store)
    app.app.on_startup.clear()
    store.admit_request("s", "check my notes", request_id="req-live")

    class Runtime:
        def run_subordinate_react(self, prompt, *, callbacks, **_kw):
            agent = JaegerAgent(adapter=_Down(), fallback_adapters=[_Scripted([
                {"role": "assistant", "content": None,
                 "tool_calls": [{"id": "call_notes", "name": "look_up_notes", "arguments": {"topic": "trip"}}]},
                {"role": "assistant", "content": "Your notes are fine."},
            ])], callbacks=callbacks)
            text = agent.run_turn(prompt)
            return {"text": text, "halt_reason": agent.last_halt_reason, "iterations": agent.last_iteration_count}

    from jaeger_ai.core.entity.runtime import EntityRuntime
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: Runtime()))
    result = app._owner_react_turn("check my notes", session_key="s", request_id="req-live", execution={})
    app._persist_terminal("req-live", "s", "completed", {"output": result["text"]},
                          assistant_text=result["text"], record_entity_event=False)
    yield app
    clear_registry()


async def _sse_frames(app, want: set[str], timeout: float = 10.0) -> list[dict]:
    frames: list[dict] = []
    async with TestClient(TestServer(app.app), headers=client_headers("webui")) as client:
        resp = await client.get("/v1/sessions/s/stream?scope=session&last_event_id=0")
        assert resp.status == 200

        async def read():
            while not want <= {f["event"] for f in frames}:
                block = (await resp.content.readuntil(b"\n\n")).decode()
                fields = dict(line.split(": ", 1) for line in block.strip().splitlines() if not line.startswith(":"))
                if "data" in fields:
                    frames.append({"event": fields.get("event"), "id": fields.get("id"), **json.loads(fields["data"])})
        try:
            await asyncio.wait_for(read(), timeout)
        finally:
            resp.close()
    return frames


def _first(frames, name):
    return next(f for f in frames if f["event"] == name)


RESPONSIBILITIES = {
    "models": {"model.started", "model.finished"},
    "tools": {"tool.started", "tool.completed"},
    "execution_loop": {"loop.iteration", "loop.stop"},
    "state_memory": {"state.memory", "state.saved"},
    "permissions": {"policy.decision"},
    "orchestration": {"route.selected", "subagent.started", "subagent.finished"},
    "reliability": {"reliability.fallback"},
    "events": {"stream.status"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("responsibility", sorted(RESPONSIBILITIES))
async def test_responsibility_arrives_live_over_sse(turn, responsibility):
    want = RESPONSIBILITIES[responsibility]
    frames = await _sse_frames(turn, want | {"loop.stop", "state.saved"})  # read the whole turn
    seen = {f["event"] for f in frames}
    assert want <= seen, f"{responsibility}: missing {want - seen}"
    if responsibility == "models":
        finished = [f["data"] for f in frames if f["event"] == "model.finished"]
        failed, done = finished[0], finished[-1]
        assert failed["ok"] is False and failed["error"] == "RuntimeError"  # the down adapter, reported
        assert done["ok"] is True and done["model"] == "scripted-model" and done["provider"] and "duration_ms" in done
    if responsibility == "tools":
        started, completed = _first(frames, "tool.started"), _first(frames, "tool.completed")
        assert started["data"]["call_id"].endswith("call_notes") and started["data"]["call_id"] == completed["data"]["call_id"]
        assert started["trace"]["kind"] == "tool"
    if responsibility == "execution_loop":
        its = [f["data"] for f in frames if f["event"] == "loop.iteration"]
        assert [i["decision"] for i in its] == ["continue", "answer"]
        assert _first(frames, "loop.stop")["data"]["reason"] == "final_answer"
    if responsibility == "state_memory":
        mem = _first(frames, "state.memory")["data"]
        assert mem["op"] == "read" and mem["fn"] == "recall" and mem["call_id"].endswith("call_notes")
        assert _first(frames, "state.saved")["data"]["status"] == "completed"
    if responsibility == "permissions":
        decision = _first(frames, "policy.decision")["data"]
        assert decision["tool"] == "look_up_notes" and decision["decision"] in {"allow", "deny", "needs_approval"}
    if responsibility == "orchestration":
        assert _first(frames, "subagent.started")["trace"]["parent_span_id"].startswith("tool:")
        assert _first(frames, "route.selected")["data"]["reason"]
    if responsibility == "reliability":
        fb = _first(frames, "reliability.fallback")["data"]
        assert fb["from"] == "down-adapter" and fb["to"] == "scripted-adapter" and "RuntimeError" in fb["reason"]
    if responsibility == "events":
        status = frames[0]
        assert status["event"] == "stream.status" and status["id"] is None  # never moves a cursor
        assert status["data"]["state"] == "connected" and status["data"]["replaying"] > 0
