"""The vision tool reuses Jaeger's active local brain and projector."""

from types import SimpleNamespace

import pytest

from jaeger_agent.tools import vision


@pytest.fixture(autouse=True)
def _reset_vision_state():
    saved = dict(vision._vision_state)
    saved_fallback = vision._native_vision_fallback
    vision._vision_state.update(node=None, handler=None, model_path=None)
    vision.bind_native_vision(None)
    yield
    vision._vision_state.clear()
    vision._vision_state.update(saved)
    vision._native_vision_fallback = saved_fallback


def test_native_vision_rejects_missing_local_brain(monkeypatch):
    with pytest.raises(RuntimeError, match="active local llama.cpp brain"):
        vision._ensure_native_vision()


def test_existing_projector_is_attached_to_prebuilt_aux_context():
    handler = object()
    worker = SimpleNamespace(chat_handler=handler)
    aux = SimpleNamespace(chat_handler=None)
    client = SimpleNamespace(llm=worker, _aux_llm=aux, chat=lambda *_a, **_k: None)
    vision.bind_native_vision(client)

    resolved_client, resolved_handler = vision._ensure_native_vision()

    assert resolved_client is client
    assert resolved_handler is handler
    assert aux.chat_handler is handler


def test_request_scope_overrides_and_restores_process_binding():
    one = SimpleNamespace(llm=SimpleNamespace(chat_handler="one"), chat=lambda: None)
    two = SimpleNamespace(llm=SimpleNamespace(chat_handler="two"), chat=lambda: None)
    vision.bind_native_vision(one)

    with vision.native_vision_scope(two):
        assert vision._ensure_native_vision() == (two, "two")
    assert vision._ensure_native_vision() == (one, "one")
