"""One routing decision for the Gateway's direct model lanes: the existing router's."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.events import JaegerEvent
from jaeger_ai.core.entity.runtime import EntityRuntime, PreparedTurn
from jaeger_ai.core.gateway.server import DEFAULT_OLLAMA_MODEL, JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


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
    used = []

    async def chat(prompt, *, model, **kwargs):
        used.append((model, kwargs.get("provider"), callable(kwargs.get("on_delta"))))
        return "ok"

    monkeypatch.setattr(app, "_model_chat", chat)
    for rid, text in (("r1", "what is a heat exchanger?"), ("r2", "my password is hunter2, remember it")):
        admitted = app.store.admit_request("s", text, request_id=rid)
        await app._execute_turn("s", admitted["turn_id"], text, request_id=rid,
                                execution={"model": "kimi-k2.7-code:cloud", "provider": "ollama", "options": {}})

    assert used == [("kimi-k2.7-code:cloud", "ollama", True)] * 2
    # Full-payload policy is tested at the actual adapter boundary, not mocked here.
