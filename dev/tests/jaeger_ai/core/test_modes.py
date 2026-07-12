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
    assert info["model"] == high_model
    assert "normal" in info["options"]
    _reset()


def test_get_mode_tool_registered() -> None:
    from jaeger_os.core.tools import tool_registry as R
    import jaeger_ai.main as m
    m._register_builtins(object())
    assert "get_mode" in {t.name for t in R.get_tools()}
