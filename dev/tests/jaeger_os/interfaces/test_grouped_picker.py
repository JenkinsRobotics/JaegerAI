"""Hermes-style two-stage /model picker.

Ports Hermes's ``_get_model_picker_display`` + ``_handle_model_picker_selection``
into Jaeger: stage 1 picks a provider, stage 2 picks a model under it, with
"← Back" + "Cancel" rows at the bottom of stage 2. These tests pin the
pure renderer + the state-machine handler. The interactive prompt_toolkit
loop itself is not unit-tested here.
"""

from __future__ import annotations

from jaeger_os.interfaces.tui.picker import (
    _PICKER_TYPE_A_MODEL,
    _compute_picker_viewport,
    _handle_picker_enter,
    _render_model_picker,
)


def _frame(state: dict, *, term_rows: int = 30) -> str:
    return "".join(text for _style, text in _render_model_picker(state, term_rows))


def _providers_two() -> list[dict]:
    return [
        {"slug": "local",        "name": "llama.cpp (in-process)",
         "models": ["gemma-4-26b", "qwen3-coder-30b"], "is_current": False},
        {"slug": "lmstudio",     "name": "LM Studio",
         "models": ["gemma-4-26b-a4b"], "is_current": True},
        {"slug": "openai",       "name": "OpenAI",
         "type_a_model": True, "is_current": False},
    ]


# ── stage 1 — provider picker ────────────────────────────────────────


def test_stage_one_title_and_provider_rows():
    state = {
        "stage": "provider", "providers": _providers_two(), "selected": 0,
        "current_model": "gemma-4-26b-a4b", "current_provider": "lmstudio",
    }
    out = _frame(state)
    assert "⚙ Model Picker — Select Provider" in out
    assert "llama.cpp (in-process) (2 models)" in out
    assert "LM Studio (1 model)" in out
    assert "OpenAI (type a model)" in out
    assert "Cancel" in out


def test_stage_one_current_provider_gets_arrow():
    state = {
        "stage": "provider", "providers": _providers_two(), "selected": 0,
        "current_model": "gemma-4-26b-a4b", "current_provider": "lmstudio",
    }
    out = _frame(state)
    # The LM Studio row carries the "← current" badge.
    lm_line = next(ln for ln in out.split("\n") if "LM Studio" in ln)
    assert "← current" in lm_line


def test_stage_one_cursor_glyph_on_selected_row():
    state = {
        "stage": "provider", "providers": _providers_two(), "selected": 1,
        "current_model": "x", "current_provider": "y",
    }
    out = _frame(state)
    lm_line = next(ln for ln in out.split("\n") if "LM Studio" in ln)
    other_line = next(ln for ln in out.split("\n") if "llama.cpp" in ln)
    assert "❯ LM Studio" in lm_line
    assert "❯" not in other_line


# ── stage 2 — model picker ───────────────────────────────────────────


def test_stage_two_title_and_rows_include_back_and_cancel():
    state = {
        "stage": "model",
        "provider_data": {"slug": "lmstudio", "name": "LM Studio"},
        "model_list": ["gemma-4-26b-a4b", "qwen3-coder-30b"],
        "selected": 0,
    }
    out = _frame(state)
    assert "⚙ Model Picker — LM Studio" in out
    assert "Select a model (2 available)" in out
    assert "gemma-4-26b-a4b" in out
    assert "qwen3-coder-30b" in out
    assert "← Back" in out
    assert "Cancel" in out


def test_stage_two_empty_model_list_shows_hint():
    state = {
        "stage": "model",
        "provider_data": {"slug": "x", "name": "Empty Provider"},
        "model_list": [],
        "selected": 0,
    }
    out = _frame(state)
    assert "No models listed for this provider" in out
    # Only the Back + Cancel rows.
    assert "← Back" in out
    assert "Cancel" in out


# ── state-machine: Enter handler ─────────────────────────────────────


def test_enter_on_provider_drills_into_stage_two():
    state = {
        "stage": "provider", "providers": _providers_two(), "selected": 1,
    }
    done, result = _handle_picker_enter(state)
    assert done is False
    assert result is None
    assert state["stage"] == "model"
    assert state["provider_data"]["slug"] == "lmstudio"
    assert state["model_list"] == ["gemma-4-26b-a4b"]
    assert state["selected"] == 0


def test_enter_on_provider_cancel_returns_none():
    providers = _providers_two()
    state = {"stage": "provider", "providers": providers, "selected": len(providers)}
    done, result = _handle_picker_enter(state)
    assert done is True
    assert result is None


def test_enter_on_type_a_model_provider_returns_sentinel():
    providers = _providers_two()
    # OpenAI is the type_a_model entry at index 2.
    state = {"stage": "provider", "providers": providers, "selected": 2}
    done, result = _handle_picker_enter(state)
    assert done is True
    assert result == ("openai", _PICKER_TYPE_A_MODEL)


def test_enter_on_model_returns_provider_and_model():
    state = {
        "stage": "model",
        "provider_data": {"slug": "lmstudio", "name": "LM Studio"},
        "model_list": ["gemma-4-26b-a4b", "qwen3-coder-30b"],
        "selected": 1,
        "providers": _providers_two(),
    }
    done, result = _handle_picker_enter(state)
    assert done is True
    assert result == ("lmstudio", "qwen3-coder-30b")


def test_enter_on_back_returns_to_stage_one():
    state = {
        "stage": "model",
        "provider_data": {"slug": "lmstudio", "name": "LM Studio"},
        "model_list": ["gemma-4-26b-a4b"],
        "selected": 1,  # ← Back position
        "providers": _providers_two(),
    }
    done, result = _handle_picker_enter(state)
    assert done is False
    assert result is None
    assert state["stage"] == "provider"
    # Cursor returns to the provider we drilled into.
    assert state["selected"] == 1


def test_enter_on_model_cancel_returns_none():
    state = {
        "stage": "model",
        "provider_data": {"slug": "lmstudio", "name": "LM Studio"},
        "model_list": ["only-one"],
        "selected": 2,  # Cancel position
        "providers": _providers_two(),
    }
    done, result = _handle_picker_enter(state)
    assert done is True
    assert result is None


# ── viewport scrolling ──────────────────────────────────────────────


def test_viewport_fits_short_list_without_scroll():
    offset, visible = _compute_picker_viewport(
        selected=2, scroll_offset=0, n=5, term_rows=30,
    )
    assert offset == 0
    assert visible == 5


def test_viewport_scrolls_to_keep_selected_in_view():
    # Long list: selected is past the visible window → offset shifts.
    offset, visible = _compute_picker_viewport(
        selected=20, scroll_offset=0, n=40, term_rows=14,
    )
    assert visible <= 14
    assert offset <= 20 <= offset + visible - 1
