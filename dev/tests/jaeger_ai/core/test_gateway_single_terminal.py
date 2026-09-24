"""One request, one terminal result: the main loop's answer, recorded once.

Unit test of the Gateway contract. Live defect (audit Task A, 2026-09-21): a
model runner persisted a terminal result every time it was called, so the operator
received candidate plans as the answer and the executor's later failure was
swallowed as a replay of an already-completed request. The turn is now a single
call into the agent loop, wrapped by the memory read (``prepare_turn``) and write
(``finish_turn``); the invariant is that exactly one terminal is published and it
is the agent loop's outcome.
"""
from __future__ import annotations

import pytest

from types import SimpleNamespace

from jaeger_ai.core.entity.runtime import EntityRuntime, PreparedTurn
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class _StubRuntime:
    """The two calls the Gateway makes around the main loop, recorded."""

    def __init__(self, background: str = "") -> None:
        self.background = background
        self.prepared: list[str] = []
        self.finished: list[tuple[str, str]] = []

    def prepare_turn(self, text, *, session_id, **_):
        self.prepared.append(text)
        return PreparedTurn(prompt=self.background + text, event=SimpleNamespace(event_id="e1"),
                            user_text=text, session_id=session_id)

    def finish_turn(self, prepared, response_text):
        self.finished.append((prepared.user_text, response_text))


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "terminal.sqlite3"))
    app.store.ensure_session("s")
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)

    async def candidate_plans(*args, **kwargs):
        return '[{"name": "candidate plan"}]'

    monkeypatch.setattr(app, "_ollama_chat", candidate_plans)
    return app


def _terminal_events(app):
    return [
        e for e in app.event_bus.get_replay_events("s", since_event_id=0)
        if e.event in {"turn.finish", "turn.failed", "turn.unknown", "turn.cancelled"}
    ]


def _agent_loop(monkeypatch, app, result):
    calls = []

    def owner_react(prompt, **kwargs):
        calls.append(prompt)
        return dict(result)

    monkeypatch.setattr(app, "_owner_react_turn", owner_react)
    return calls


@pytest.mark.asyncio
async def test_the_answer_is_the_agent_loops_text_recorded_once(app, monkeypatch):
    runtime = _StubRuntime()
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    calls = _agent_loop(monkeypatch, app, {"text": "Created workspace/audit/task_a/notes.md", "error": None})
    admitted = app.store.admit_request("s", "make the files", request_id="r1")

    await app._execute_turn("s", admitted["turn_id"], "make the files", request_id="r1")

    [finish] = _terminal_events(app)
    assert finish.event == "turn.finish"
    assert finish.data["output"] == "Created workspace/audit/task_a/notes.md"
    assert app.store.get_request("r1")["result"]["output"] == "Created workspace/audit/task_a/notes.md"
    assert calls == ["make the files"]
    assert runtime.prepared == ["make the files"]
    assert runtime.finished == [("make the files", "Created workspace/audit/task_a/notes.md")]


@pytest.mark.asyncio
async def test_a_failure_is_reported_as_a_failure_and_records_no_answer(app, monkeypatch):
    runtime = _StubRuntime()
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    _agent_loop(monkeypatch, app, {"text": "", "error": "400 invalid model name"})
    admitted = app.store.admit_request("s", "make the files", request_id="r2")

    await app._execute_turn("s", admitted["turn_id"], "make the files", request_id="r2")

    [terminal] = _terminal_events(app)
    assert terminal.event == "turn.failed"
    assert "invalid model name" in terminal.data["error"]
    assert app.store.get_request("r2")["status"] == "failed"
    assert runtime.finished == []


@pytest.mark.asyncio
async def test_the_agent_sees_the_request_with_its_recalled_memory(app, monkeypatch):
    runtime = _StubRuntime(background="<background>you were told: token VEGA</background>\n\n")
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    calls = _agent_loop(monkeypatch, app, {"text": "VEGA", "error": None})
    admitted = app.store.admit_request("s", "what is my token?", request_id="r6")

    await app._execute_turn("s", admitted["turn_id"], "what is my token?", request_id="r6")

    assert calls == ["<background>you were told: token VEGA</background>\n\nwhat is my token?"]


@pytest.mark.asyncio
async def test_unavailable_memory_never_stops_the_operators_request(app, monkeypatch):
    class Broken(_StubRuntime):
        def prepare_turn(self, text, **kw):
            raise OSError("event store unavailable")

    runtime = Broken()
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    calls = _agent_loop(monkeypatch, app, {"text": "done", "error": None})
    admitted = app.store.admit_request("s", "do it", request_id="r7")

    await app._execute_turn("s", admitted["turn_id"], "do it", request_id="r7")

    [finish] = _terminal_events(app)
    assert finish.event == "turn.finish" and finish.data["output"] == "done"
    assert calls == ["do it"]  # the bare request, unadorned
    assert runtime.finished == []


@pytest.mark.asyncio
async def test_a_failure_recording_the_answer_does_not_undo_the_answer(app, monkeypatch):
    class BrokenWrite(_StubRuntime):
        def finish_turn(self, prepared, response_text):
            raise OSError("disk full")

    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: BrokenWrite()))
    _agent_loop(monkeypatch, app, {"text": "answer", "error": None})
    admitted = app.store.admit_request("s", "q", request_id="r8")

    await app._execute_turn("s", admitted["turn_id"], "q", request_id="r8")

    [finish] = _terminal_events(app)
    assert finish.event == "turn.finish" and finish.data["output"] == "answer"


_ReActRuntime = _StubRuntime


@pytest.fixture
def image_session(app, tmp_path, monkeypatch):
    lanes = []

    async def vision_chat(*args, **kwargs):
        lanes.append("vision_chat")
        return "the square is blue"

    async def no_native(*args, **kwargs):
        return None

    def owner_react(prompt, **kwargs):
        lanes.append("entity_react")
        return {
            "text": "saved workspace/audit/task_g/phrase.txt",
            "halt_reason": None,
        }

    monkeypatch.setattr(app, "_ollama_chat", vision_chat)
    monkeypatch.setattr(app, "_native_lead_turn", no_native)
    monkeypatch.setattr(app, "_owner_react_turn", owner_react)
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: _ReActRuntime()))
    monkeypatch.setattr(EntityRuntime, "subordinate_model_name", lambda self: "ollama:test", raising=False)
    app.store.add_attachment("s", {"safe_path": str(tmp_path / "panel.png"), "original_filename": "panel.png",
                                   "mime_type": "image/png"})
    return lanes


@pytest.mark.asyncio
async def test_in_an_image_session_work_goes_through_the_entity(app, image_session):
    """Live defect: "save the phrase to a file" in an image session was sent
    to a tool-less vision chat, answered "I'll create the file", and recorded
    as completed with nothing written."""
    admitted = app.store.admit_request("s", "Save the phrase into workspace/audit/task_g/phrase.txt", request_id="r3")

    await app._execute_turn("s", admitted["turn_id"], "Save the phrase into workspace/audit/task_g/phrase.txt",
                            request_id="r3")

    assert image_session == ["entity_react"]


@pytest.mark.asyncio
async def test_in_an_image_session_a_question_goes_to_vision(app, image_session):
    admitted = app.store.admit_request("s", "What colour is the square?", request_id="r4")

    await app._execute_turn("s", admitted["turn_id"], "What colour is the square?", request_id="r4")

    assert image_session == ["vision_chat"]


@pytest.mark.asyncio
async def test_an_image_name_in_recalled_history_does_not_make_an_image_turn(app, monkeypatch):
    lanes = []

    def _RecallingRuntime():
        return _StubRuntime(background="<background>- human.message: what is in panel.png?</background>\n\n")

    async def vision_chat(*args, **kwargs):
        lanes.append("vision_chat")
        return "blue"

    async def no_native(*args, **kwargs):
        return None

    monkeypatch.setattr(app, "_ollama_chat", vision_chat)
    monkeypatch.setattr(app, "_native_lead_turn", no_native)
    monkeypatch.setattr(
        app,
        "_owner_react_turn",
        lambda prompt, **kw: (
            lanes.append("entity_react")
            or {"text": "NOVA", "halt_reason": None}
        ),
    )
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: _RecallingRuntime()))
    monkeypatch.setattr(EntityRuntime, "subordinate_model_name", lambda self: "ollama:test", raising=False)
    admitted = app.store.admit_request("s", "What is my audit memory token?", request_id="r5")

    await app._execute_turn("s", admitted["turn_id"], "What is my audit memory token?", request_id="r5")

    assert lanes == ["entity_react"]
