"""One routing decision for the Gateway's direct model lanes: the existing router's."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.events import JaegerEvent
from jaeger_ai.core.entity.runtime import EntityRuntime, PreparedTurn
from jaeger_ai.core.gateway.server import DEFAULT_OLLAMA_MODEL, JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.models.router import _DEFAULT_LOCAL


def test_public_text_uses_the_requested_model_and_blank_uses_the_default():
    assert JaegerGatewayApp._lane_model("what is a heat exchanger?", "@ollama-cloud:glm-5.3-flash:cloud") == "glm-5.3-flash:cloud"
    assert JaegerGatewayApp._lane_model("what is a heat exchanger?", None) == DEFAULT_OLLAMA_MODEL


def test_private_text_never_reaches_a_cloud_model():
    chosen = JaegerGatewayApp._lane_model("my password is hunter2, store it", "kimi-k2.7-code:cloud")
    assert chosen == _DEFAULT_LOCAL
    assert not chosen.endswith(":cloud")


@pytest.mark.asyncio
async def test_a_text_only_turn_is_routed_by_what_the_operator_wrote(tmp_path, monkeypatch):
    runtime = SimpleNamespace(
        executive_selector=None, current_state=SimpleNamespace(active_goals=[]),
        identity=SimpleNamespace(entity_id="e", display_name="Jaeger"), layout=None,
        prepare_turn=lambda text, *, session_id, **_: PreparedTurn(
            prompt="<background>nothing private</background>\n\n" + text,
            event=JaegerEvent.human_message(text, actor="human:operator", source="gateway", session_id=session_id),
            user_text=text, session_id=session_id),
        finish_turn=lambda prepared, response_text: None,
    )
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "g.sqlite3"))
    app.store.ensure_session("s", metadata={"execution_mode": "text_only"})
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)
    used: list[str] = []

    async def chat(prompt, *, model, **kwargs):
        used.append(model)
        return "ok"

    monkeypatch.setattr(app, "_ollama_chat", chat)
    for rid, text in (("r1", "what is a heat exchanger?"), ("r2", "my password is hunter2, remember it")):
        admitted = app.store.admit_request("s", text, request_id=rid)
        await app._execute_turn("s", admitted["turn_id"], text, request_id=rid,
                                execution={"model": "kimi-k2.7-code:cloud", "options": {}})

    assert used == ["kimi-k2.7-code:cloud", _DEFAULT_LOCAL]
