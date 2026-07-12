"""KV-prewarm is decoupled from voice-model warmup.

The windowed app boots with warmup=False to skip the heavy whisper/kokoro
preloads — but it must STILL prewarm the LLM (system prompt + tool schemas) so
the first user turn isn't a ~26s cold prefill. Regression guard so the two
never get re-coupled.
"""

import inspect


def test_boot_for_tui_exposes_prewarm_model() -> None:
    from jaeger_ai.main import boot_for_tui
    assert "prewarm_model" in inspect.signature(boot_for_tui).parameters


def test_agentcore_prewarms_model_even_with_voice_warmup_off(monkeypatch) -> None:
    import jaeger_ai.main as m

    captured: dict = {}

    class _FakeBoot:
        client = object()

        def cleanup(self) -> None:
            pass

    def _fake_boot(**kw):
        captured.update(kw)
        return _FakeBoot()

    monkeypatch.setattr(m, "boot_for_tui", _fake_boot)

    from jaeger_ai.agent.loop.agent_core import AgentCore
    AgentCore(bus=object(), warmup=False)

    assert captured.get("prewarm_model") is True   # LLM still primed → warm first turn
    assert captured.get("warmup") is False         # voice models still skipped
