"""Tests for the agent_status indicator — Phase-9 live status bar."""

from __future__ import annotations

import time

import pytest

from jaeger_os.main import (
    _pipeline,
    get_agent_status,
    request_turn_cancel,
    set_agent_status,
    status_label,
)


@pytest.fixture(autouse=True)
def _reset_status():
    """Every test starts with a known idle state."""
    set_agent_status("ready", "")
    old_cancel = _pipeline.get("cancel_event")
    old_agent = _pipeline.get("active_jaeger_agent")
    _pipeline["cancel_event"] = None
    _pipeline["active_jaeger_agent"] = None
    yield
    _pipeline["cancel_event"] = old_cancel
    _pipeline["active_jaeger_agent"] = old_agent
    set_agent_status("ready", "")


def test_set_get_round_trip():
    set_agent_status("tool", "web_search")
    snap = get_agent_status()
    assert snap["state"] == "tool"
    assert snap["detail"] == "web_search"
    assert snap["since_ts"] > 0


def test_default_state_is_ready():
    snap = get_agent_status()
    assert snap["state"] == "ready"


def test_set_clears_detail_when_not_provided():
    set_agent_status("tool", "X")
    set_agent_status("thinking")  # no detail
    snap = get_agent_status()
    assert snap["state"] == "thinking"
    assert snap["detail"] == ""


def test_status_label_shows_state_and_detail():
    set_agent_status("tool", "web_search")
    # Sleep enough that the (>=0.5s) elapsed bracket appears.
    time.sleep(0.6)
    label = status_label()
    assert "tool" in label
    assert "web_search" in label
    assert "s)" in label  # elapsed suffix


def test_status_label_ready_omits_elapsed():
    set_agent_status("ready", "")
    time.sleep(0.6)
    label = status_label()
    # Ready never shows the elapsed bracket (it's the idle state).
    assert "ready" in label
    assert "s)" not in label


def test_status_label_glyph_for_each_state():
    """Every documented state maps to a known glyph."""
    expected = {
        "ready": "o",
        "thinking": "(...)",
        "tool": ">",
        "finalize": "*",
        "deep_think": "DT",
        "background": "BG",
        "error": "!",
        "speaking": "TTS",
    }
    for state, glyph in expected.items():
        set_agent_status(state, "")
        label = status_label()
        assert label.startswith(glyph), f"{state!r} missing glyph {glyph!r}: {label!r}"


def test_status_label_unknown_state_uses_fallback_glyph():
    set_agent_status("custom_state", "x")
    label = status_label()
    assert label.startswith("*")  # fallback glyph


def test_status_label_accepts_explicit_snapshot():
    """Passing an explicit snapshot avoids re-read races (the TUI
    captures one snapshot per render tick)."""
    snap = {"state": "tool", "detail": "calculate", "since_ts": time.time()}
    label = status_label(snap)
    assert "tool" in label
    assert "calculate" in label


def test_status_label_handles_missing_fields():
    """Defensive: a malformed snapshot dict shouldn't crash the
    renderer — the status indicator is non-critical."""
    label = status_label({})
    assert isinstance(label, str)
    assert len(label) > 0


def test_pipeline_carries_agent_status_by_default():
    """At import time the pipeline dict ships the agent_status slot —
    callers don't need a setup step."""
    assert "agent_status" in _pipeline
    assert _pipeline["agent_status"]["state"] in ("ready", "")


def test_since_ts_advances_on_state_change():
    set_agent_status("tool", "x")
    first_ts = get_agent_status()["since_ts"]
    time.sleep(0.05)
    set_agent_status("thinking")
    second_ts = get_agent_status()["since_ts"]
    assert second_ts > first_ts


def test_request_turn_cancel_interrupts_active_jaeger_agent():
    """The TUI cancel event must reach the Phase-9 agent's own
    interrupt event, not only the process-wide tool interrupt flag."""
    calls: list[int] = []

    class _Agent:
        def interrupt(self) -> None:
            calls.append(1)

    _pipeline["active_jaeger_agent"] = _Agent()
    request_turn_cancel()
    assert calls == [1]
