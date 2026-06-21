"""TUI turn rendering — the hermes-style chrome.

Each turn is framed like hermes: the user message between two rules on
a ``●`` bullet, live ``┊`` tool-activity lines while the agent works,
the reply in a ``✦ <name>`` rule-labelled box, and a pinned bottom
toolbar (model · context gauge · uptime · response time).
"""

from __future__ import annotations

from rich.console import Console

from jaeger_os.interfaces.tui.app import (
    JaegerTUI,
    _format_elapsed,
    _kfmt,
    _pct_color,
)


def _tui() -> JaegerTUI:
    tui = JaegerTUI(skip_model=True)
    tui.console = Console(width=90)
    return tui


# ── formatting helpers ───────────────────────────────────────────────


def test_kfmt_compacts_thousands() -> None:
    """Ported from Hermes's ``format_token_count_compact`` — K/M/B with
    smart precision and trailing zeros trimmed."""
    assert _kfmt(27800) == "27.8K"
    assert _kfmt(262144) == "262K"
    assert _kfmt(1_500_000) == "1.5M"
    assert _kfmt(980) == "980"
    assert _kfmt(0) == "0"


def test_format_elapsed_keeps_seconds_visible() -> None:
    """Hermes-faithful: seconds stay visible at every scale, so the
    status-bar timer increments smoothly (no ``65s → 1m`` jump that
    drops the seconds digit)."""
    assert _format_elapsed(12) == "12s"
    assert _format_elapsed(65) == "1m 5s"
    assert _format_elapsed(240) == "4m"            # 4 min exact → no seconds
    assert _format_elapsed(3600) == "1h 0m"        # 1h exact   → no seconds
    assert _format_elapsed(3690) == "1h 1m 30s"    # mixed      → keep seconds
    assert _format_elapsed(90061) == "1d 1h 1m"    # days drop seconds


def test_format_elapsed_with_emoji_picks_live_vs_frozen() -> None:
    assert _format_elapsed(23, with_emoji=True) == "⏲ 23s"
    assert _format_elapsed(23, live=True, with_emoji=True) == "⏱ 23s"


def test_pct_color_follows_hermes_good_warn_bad_critical_bands() -> None:
    assert "green" in _pct_color(0)
    assert "green" in _pct_color(49)
    assert "yellow" in _pct_color(50)
    assert "yellow" in _pct_color(80)
    assert "red" in _pct_color(81)
    assert "bright" in _pct_color(95) and "red" in _pct_color(95)


# ── turn header ──────────────────────────────────────────────────────


def test_turn_header_frames_the_user_message() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_turn_header("hello there", source="text")
    out = cap.get()
    assert "hello there" in out
    assert "●" in out
    assert out.count("─") > 20          # a rule above and below


def test_turn_header_glyph_per_source() -> None:
    tui = _tui()
    for source, glyph in (("text", "●"), ("voice", "🎙"), ("goal", "◎")):
        with tui.console.capture() as cap:
            tui._render_turn_header("x", source=source)
        assert glyph in cap.get()


def test_turn_header_does_not_interpret_markup() -> None:
    # A user message containing Rich markup must render literally.
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_turn_header("delete [red]everything[/red]", source="text")
    assert "[red]everything[/red]" in cap.get()


# ── answer box ───────────────────────────────────────────────────────


def test_render_answer_labels_with_the_agent_name() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_answer("the capital of France is Paris")
    out = cap.get()
    assert "the capital of France is Paris" in out
    assert "✦" in out                   # the answer-box label glyph


def test_render_answer_error_path() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_answer("", error="model timed out")
    out = cap.get()
    assert "model timed out" in out
    assert "error" in out


def test_render_answer_empty_is_silent() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_answer("   ")
    assert cap.get().strip() == ""


# ── live tool activity ───────────────────────────────────────────────


def test_tool_event_start_sets_activity_label() -> None:
    tui = _tui()
    tui._on_tool_event("start", "web_search", "weather", 0.0)
    assert tui._current_activity == "web_search"


def test_tool_event_done_prints_a_line_and_resets() -> None:
    tui = _tui()
    tui._on_tool_event("start", "web_search", "weather", 0.0)
    with tui.console.capture() as cap:
        tui._on_tool_event("done", "web_search", "", 1.4)
    out = cap.get()
    assert "┊" in out and "web_search" in out and "1.4s" in out
    assert tui._current_activity == "ruminating"


# ── status bar (pinned above the input line) ─────────────────────────


def test_status_line_has_the_hermes_segments() -> None:
    tui = _tui()
    tui.model_name = "qwen3.5:397b"
    tui._context_tokens = 27800
    tui._context_max = 262144
    tui._last_turn_s = 23.0
    bar = tui._status_line()
    assert "qwen3.5:397b" in bar
    # Hermes's format_token_count_compact strips trailing zeros — 262144
    # rounds to "262K" (no ".1"), 27800 keeps the digit as "27.8K".
    assert "27.8K/262K" in bar
    assert "%" in bar and "█" in bar     # the context gauge
    assert "⏲ 23s" in bar


def test_status_line_shows_spinner_while_running() -> None:
    tui = _tui()
    tui._turn_running.set()
    tui._current_activity = "web_search"
    assert "web_search" in tui._status_line()


def test_prompt_message_puts_input_last() -> None:
    # The ❯ input fragment must be the final fragment — the input line
    # sits below the status bar (hermes layout).
    tui = _tui()
    frags = tui._prompt_message()
    assert frags[-1][1] == "❯ "
    assert any("─" in text for _style, text in frags)   # the bar rules


def test_prompt_message_is_just_the_caret_when_bar_hidden() -> None:
    from jaeger_os.interfaces.tui.theme import ACCENT_PTK
    tui = _tui()
    tui._statusbar_on = False
    frags = tui._prompt_message()
    assert frags == [(f"fg:{ACCENT_PTK} bold", "❯ ")]


# ── ctx gauge: bugfix coverage ────────────────────────────────────────


def test_ctx_max_prefers_client_loaded_ctx_over_config(monkeypatch) -> None:
    """Status gauge denominator must come from the LOADED model's
    actual ctx (``client.loaded_ctx``), not just the config value.
    Otherwise a `/switch-model` to a fatter ctx isn't reflected until
    the config file is edited — exactly the wrong direction."""
    import jaeger_os.main as main

    class _StubClient:
        loaded_ctx = 32_768
        native_ctx_max = 262_144

    class _StubCfg:
        class model:
            ctx = 8192   # what the wizard wrote — should LOSE to the live client

    monkeypatch.setitem(main._pipeline, "client", _StubClient())
    monkeypatch.setitem(main._pipeline, "config", _StubCfg())

    tui = _tui()
    assert tui._current_ctx_max() == 32_768
    assert tui._current_native_ctx_max() == 262_144


def test_ctx_max_falls_back_to_config_when_client_lacks_loaded_ctx(monkeypatch) -> None:
    """Older clients (cloud adapters, MLX) don't expose ``loaded_ctx``.
    We must still produce a sensible denominator from config."""
    import jaeger_os.main as main

    class _OldClient:
        pass  # no loaded_ctx attribute

    class _StubCfg:
        class model:
            ctx = 16_384

    monkeypatch.setitem(main._pipeline, "client", _OldClient())
    monkeypatch.setitem(main._pipeline, "config", _StubCfg())

    tui = _tui()
    assert tui._current_ctx_max() == 16_384


def test_context_estimate_counts_phase9_dict_messages(monkeypatch) -> None:
    """The Phase-9 agent loop produces TypedDict messages with
    ``msg['content']`` directly — not the legacy pydantic-ai
    ``msg.parts[].content`` shape. The estimator was iterating only the
    legacy shape, so the new-loop sessions always read 0%. Pin both
    shapes count."""
    import jaeger_os.main as main

    fake_history = [
        {"role": "user", "content": "x" * 400},
        {"role": "assistant", "content": "y" * 800,
         "tool_calls": [{"id": "c1", "name": "get_time",
                         "arguments": {"timezone": "UTC"}}]},
        {"role": "tool", "tool_call_id": "c1",
         "name": "get_time", "content": "noon"},
    ]
    monkeypatch.setattr(main, "_get_session_history",
                        lambda key: fake_history)

    tui = _tui()
    tui._refresh_context_estimate()
    # ~ (400 + 800 + 4 + 20 + 8 + 4) / 4 — exact arithmetic isn't the
    # point; we just need it to be non-zero for the dict shape.
    assert tui._context_tokens > 100, (
        "Phase-9 dict messages produced 0 tokens — the estimator "
        "isn't counting the new shape"
    )


def test_context_estimate_still_counts_legacy_parts_shape(monkeypatch) -> None:
    """Backward-compat: the same estimator must still handle the
    pydantic-ai ``msg.parts[].content`` shape so a hybrid session
    (early turns on legacy, later on Phase-9) still gauges correctly."""
    import jaeger_os.main as main
    from types import SimpleNamespace

    legacy_msg = SimpleNamespace(parts=[
        SimpleNamespace(content="hello " * 200),
        SimpleNamespace(content="world " * 100),
    ])
    monkeypatch.setattr(main, "_get_session_history",
                        lambda key: [legacy_msg])
    tui = _tui()
    tui._refresh_context_estimate()
    assert tui._context_tokens > 100
