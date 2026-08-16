"""Agent modes — normal / high / deep-sleep model+voice presets.

Switching the resident model is slow + heavy, so these mock main.switch_model
and assert the orchestration: model swap on change, voice toggle, idempotence,
and that the set_mode tool is registered.
"""


def _reset():
    from jaeger_ai.core.runtime import modes
    modes._state["mode"] = "normal"
    modes._state["model"] = None


def test_unknown_mode_rejected() -> None:
    from jaeger_ai.core.runtime import modes
    _reset()
    r = modes.set_mode("turbo")
    assert r["ok"] is False and "unknown mode" in r["error"]


def test_set_mode_swaps_model_and_toggles_voice(monkeypatch) -> None:
    from jaeger_ai.core.runtime import modes
    import jaeger_ai.main as m

    swapped: list = []
    monkeypatch.setattr(m, "switch_model", lambda model, **k: swapped.append(model))

    # Reference MODES dynamically — verify the orchestration, not the specific
    # model picks (which change as the benchmark moves).
    high_model = modes.MODES["high"]["model"]
    modes._state["mode"] = "normal"
    modes._state["model"] = modes.MODES["normal"]["model"]   # known resident
    assert modes.voice_enabled() is True

    r = modes.set_mode("high")
    assert r["ok"] is True and r["mode"] == "high"
    assert swapped == [high_model]                     # swapped to the high model
    assert modes.voice_enabled() is False              # voice suppressed in high

    r2 = modes.set_mode("high")                        # idempotent — no second swap
    assert r2.get("unchanged") is True
    assert swapped == [high_model]
    _reset()


def test_back_to_normal_swaps_back(monkeypatch) -> None:
    from jaeger_ai.core.runtime import modes
    import jaeger_ai.main as m
    swapped: list = []
    monkeypatch.setattr(m, "switch_model", lambda model, **k: swapped.append(model))
    modes._state["mode"] = "high"
    modes._state["model"] = modes.MODES["high"]["model"]
    r = modes.set_mode("normal")
    assert r["ok"] is True and swapped == [modes.MODES["normal"]["model"]]
    assert modes.voice_enabled() is True
    _reset()


def test_mode_state_message_shape() -> None:
    from jaeger_ai.core.messages import ModeState
    assert ModeState(mode="high").topic == "/sense/mode"


def test_set_mode_tool_registered() -> None:
    from jaeger_os.core.tools import tool_registry as R
    import jaeger_ai.main as m
    m._register_builtins(object())
    assert "set_mode" in {t.name for t in R.get_tools()}


def test_mode_info_reports_current_from_fact() -> None:
    from jaeger_ai.core.runtime import modes
    high_model = modes.MODES["high"]["model"]
    modes._state["mode"] = "high"
    modes._state["model"] = high_model
    info = modes.mode_info()
    assert info["mode"] == "high" and info["voice"] is False
    assert info["local_preset_model"] == high_model
    assert "normal" in info["options"]
    _reset()


def test_mode_info_reports_the_external_brain_when_one_is_serving(monkeypatch) -> None:
    """Status bar said DeepSeek; get_mode said Gemma. The serving
    client is the source of truth, not the idle local preset."""
    from types import SimpleNamespace

    from jaeger_ai.core.runtime import modes
    import jaeger_ai.main as main

    monkeypatch.setitem(main._pipeline, "client", SimpleNamespace(
        kind="external", provider="ollama-cloud",
        model_name="deepseek-v4-flash:preview", loaded_ctx=1_048_576,
    ))
    monkeypatch.setitem(main._pipeline, "config", SimpleNamespace(
        external_model=SimpleNamespace(
            enabled=True, provider="ollama-cloud",
            model="deepseek-v4-flash:preview", ctx=1_048_576,
        ),
        model=SimpleNamespace(model_path="/models/gemma-4-e4b-it-q4_k_m.gguf", ctx=8192),
    ))
    info = modes.mode_info()
    assert info["model"] == "deepseek-v4-flash:preview"
    assert info["provider"] == "ollama-cloud"
    assert info["kind"] == "external"
    assert info["ctx"] == 1_048_576
    assert info["local_preset_model"] == modes.MODES["normal"]["model"]
    _reset()


def test_set_mode_refuses_to_swap_local_weights_while_external_serves(monkeypatch) -> None:
    from types import SimpleNamespace

    from jaeger_ai.core.runtime import modes
    import jaeger_ai.main as main

    monkeypatch.setitem(main._pipeline, "client", SimpleNamespace(
        kind="external", provider="ollama-cloud",
        model_name="deepseek-v4-flash:preview", loaded_ctx=1_048_576,
    ))
    monkeypatch.setitem(main._pipeline, "config", SimpleNamespace(
        external_model=SimpleNamespace(
            enabled=True, provider="ollama-cloud",
            model="deepseek-v4-flash:preview", ctx=1_048_576,
        ),
        model=SimpleNamespace(model_path="/models/x.gguf", ctx=8192),
    ))
    r = modes.set_mode("high")
    assert r["ok"] is False
    assert "external brain" in r["error"]
    _reset()


def test_get_mode_tool_registered() -> None:
    from jaeger_os.core.tools import tool_registry as R
    import jaeger_ai.main as m
    m._register_builtins(object())
    assert "get_mode" in {t.name for t in R.get_tools()}
