"""One request, one terminal result — the Entity's, not a runner's.

Unit test of the Gateway contract. Live defect (audit Task A, 2026-09-21):
``_sync_model`` persisted a terminal result every time it was called. The
deliberate planner calls it for intermediate thoughts, so the operator received
four candidate plans as the answer 28 s in, and the executor's later failure
was swallowed as a replay of an already-completed request.
"""
from __future__ import annotations

import pytest

from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class _PlanningRuntime:
    """Thinks with the model first, as the deliberate planner does."""

    def __init__(self, final: dict) -> None:
        self.final = final

    def execute_turn(self, text, *, context, **_):
        context["model_runner"]("Generate three candidate plans for: " + text)
        return dict(self.final)


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


@pytest.mark.asyncio
async def test_an_intermediate_model_call_is_not_the_answer(app, monkeypatch):
    runtime = _PlanningRuntime({"text": "Created workspace/audit/task_a/notes.md", "error": None})
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    admitted = app.store.admit_request("s", "make the files", request_id="r1")

    await app._execute_turn("s", admitted["turn_id"], "make the files", request_id="r1")

    [finish] = _terminal_events(app)
    assert finish.event == "turn.finish"
    assert finish.data["output"] == "Created workspace/audit/task_a/notes.md"
    assert app.store.get_request("r1")["result"]["output"] == "Created workspace/audit/task_a/notes.md"


@pytest.mark.asyncio
async def test_a_failure_after_thinking_is_reported_as_a_failure(app, monkeypatch):
    runtime = _PlanningRuntime({"text": "", "error": "400 invalid model name"})
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    admitted = app.store.admit_request("s", "make the files", request_id="r2")

    await app._execute_turn("s", admitted["turn_id"], "make the files", request_id="r2")

    [terminal] = _terminal_events(app)
    assert terminal.event == "turn.failed"
    assert "invalid model name" in terminal.data["error"]
    assert app.store.get_request("r2")["status"] == "failed"


class _ReActRuntime:
    def execute_turn(self, text, *, context, **_):
        return dict(context["react_runner"](text))


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
        return "saved workspace/audit/task_g/phrase.txt"

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

    class _RecallingRuntime:
        def execute_turn(self, text, *, context, **_):
            recalled = "<background>- human.message: what is in panel.png?</background>\n\n" + text
            return dict(context["react_runner"](recalled))

    async def vision_chat(*args, **kwargs):
        lanes.append("vision_chat")
        return "blue"

    async def no_native(*args, **kwargs):
        return None

    monkeypatch.setattr(app, "_ollama_chat", vision_chat)
    monkeypatch.setattr(app, "_native_lead_turn", no_native)
    monkeypatch.setattr(app, "_owner_react_turn", lambda prompt, **kw: lanes.append("entity_react") or "NOVA")
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: _RecallingRuntime()))
    monkeypatch.setattr(EntityRuntime, "subordinate_model_name", lambda self: "ollama:test", raising=False)
    admitted = app.store.admit_request("s", "What is my audit memory token?", request_id="r5")

    await app._execute_turn("s", admitted["turn_id"], "What is my audit memory token?", request_id="r5")

    assert lanes == ["entity_react"]
