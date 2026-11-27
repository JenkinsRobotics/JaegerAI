from types import SimpleNamespace

from jaeger_gateway.runtime import ModularGatewayRuntime
from jaeger_loop import AgentLoop
from jaeger_models import OllamaModel, ReplayModel


def test_main_model_history_is_session_scoped_and_paged(tmp_path):
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        session = runtime.store.main_chat_session()["session_id"]
        other = runtime.store.create_session(title="Other")["session_id"]
        runtime.store.append_message(other, "user", "private to other session")
        runtime.store.append_message(session, "user", "first in main")
        for index in range(70):
            runtime.store.append_message(session, "assistant", f"progress {index}")
        runtime.model = ReplayModel([{"content": "ok"}])
        _, future = runtime.coordinator.submit(session, "next task")
        assert future.result(timeout=15)["content"] == "ok"
        contents = [row["content"] for row in runtime.model.calls[0]["messages"]]
        assert contents.count("next task") == 1
        assert contents.index("first in main") < contents.index("progress 69")
        assert "private to other session" not in contents
    finally:
        runtime.close()


def test_history_scales_with_model_window(tmp_path, monkeypatch):
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        model = ReplayModel([])
        rows = [{"role": "assistant", "content": "x" * 1000}] * 400
        def count(window):
            monkeypatch.setattr(model, "profile", lambda _: SimpleNamespace(context_window=window))
            loop = AgentLoop(model=model, tools=runtime.tools)
            return len(loop.select_history("continue", rows))
        assert 0 < count(8192) < count(65536) < len(rows)
    finally:
        runtime.close()


def test_ollama_profile_uses_selected_runner(monkeypatch):
    monkeypatch.setattr("jaeger_models.providers._get_json", lambda *args, **kwargs: {
        "models": [{"name": "other", "context_length": 4096}, {"name": "selected", "context_length": 16384}]
    })
    assert OllamaModel("selected").profile("selected").context_window == 16384
