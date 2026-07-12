"""TUI smoke tests — slash commands, status bar, banner.

End-to-end TUI behavior (REPL loop with real model load) is out of
scope for unit tests; this file covers the pieces that don't need
Gemma to verify.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from jaeger_ai.interfaces.tui import (
    banner,
    slash_commands as slash,
    status,
)
from jaeger_ai.interfaces.tui.app import JaegerTUI


# ── Banner ──────────────────────────────────────────────────────────


def test_banner_is_non_empty() -> None:
    assert banner.JAEGER_ASCII.count("\n") >= 5
    assert "JAEGER" not in banner.JAEGER_ASCII  # block-letters render
    assert banner.TAGLINE


# ── Status bar / panels ─────────────────────────────────────────────


def test_status_bar_renders_all_segments() -> None:
    bar = status.status_bar(
        model_name="gemma",
        state="thinking",
        elapsed_s=2.5,
        context_tokens=1024,
        context_max=8192,
        uptime_s=125.0,
        voice_state="off",
    )
    plain = str(bar)
    assert "gemma" in plain
    assert "thinking" in plain
    assert "1,024/8,192" in plain
    assert "up 0h 02m" in plain
    assert "mic off" in plain  # mic = the STT loop; renamed from "voice"


def test_status_bar_no_context_overflow() -> None:
    """Zero-token case shouldn't divide by zero."""
    bar = status.status_bar(
        model_name="gemma", state="ready", elapsed_s=0,
        context_tokens=0, context_max=8192, uptime_s=0, voice_state="off",
    )
    assert "0/8,192" in str(bar)


def test_boot_panel_contains_tools_block() -> None:
    panel = status.boot_panel(
        version="0.5.0",
        instance_name="default",
        model_name="gemma",
        session_id="abc12345",
        instance_dir=Path("/tmp/fake_instance"),
    )
    # Render to string for assertion — Console writes to a buffer.
    console = Console(file=open("/dev/null", "w"), width=120)
    with console.capture() as cap:
        console.print(panel)
    rendered = cap.get()
    assert "Jaeger-OS 0.5.0" in rendered
    assert "Available Tools" in rendered
    assert "memory:" in rendered
    assert "abc12345" in rendered


def test_thinking_panel_with_token_count() -> None:
    panel = status.thinking_panel("Step 1: think. Step 2: act.", tokens=468)
    console = Console(width=80)
    with console.capture() as cap:
        console.print(panel)
    rendered = cap.get()
    assert "Thinking" in rendered
    assert "~468 tokens" in rendered
    assert "Step 1" in rendered


def test_tool_activity_line_format() -> None:
    line = status.tool_activity("calculate", "= 1093", 0.001)
    plain = str(line)
    assert "calculate" in plain
    assert "= 1093" in plain
    assert "(0.00s)" in plain


# ── Slash commands ─────────────────────────────────────────────────


def _ctx() -> slash.SlashContext:
    return slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=80),
        instance_dir=Path("/tmp/fake_instance"),
    )


def test_is_slash_detects_leading_slash() -> None:
    assert slash.is_slash("/help")
    assert slash.is_slash("  /quit  ")
    assert not slash.is_slash("hello /there")
    assert not slash.is_slash("")


def test_quit_command_returns_quit_true() -> None:
    result = slash.dispatch("/quit", _ctx())
    assert result.quit is True


def test_help_command_does_not_quit() -> None:
    result = slash.dispatch("/help", _ctx())
    assert result.quit is False


def test_unknown_slash_returns_noop() -> None:
    result = slash.dispatch("/nonexistent_cmd", _ctx())
    assert result.quit is False
    assert result.message == ""


def test_instance_command_prints_path() -> None:
    ctx = _ctx()
    result = slash.dispatch("/instance", ctx)
    assert result.quit is False


# ── JaegerTUI construction ─────────────────────────────────────────


def test_lilith_tui_constructs_without_loading_model() -> None:
    """Default construction must not load Gemma — that's the
    point of skip_model + lazy ensure_agent."""
    tui = JaegerTUI(skip_model=True)
    assert tui._agent is None
    assert tui._client is None
    assert tui.session_id  # generated


def test_render_boot_doesnt_load_model() -> None:
    """Smoke: boot rendering should be safe even when no model is loaded."""
    tui = JaegerTUI(skip_model=True)
    tui.console = Console(file=open("/dev/null", "w"), width=120)
    tui.render_boot()  # would explode if it touched the agent


# ── Eager boot ──────────────────────────────────────────────────────


def test_render_boot_omits_the_prompt_hint() -> None:
    """The 'type a prompt' hint moved out of render_boot — it must not
    show until the eager boot finishes (see _print_ready_hint)."""
    tui = JaegerTUI(skip_model=True)
    tui.console = Console(width=120)
    with tui.console.capture() as cap:
        tui.render_boot()
    assert "Type a prompt" not in cap.get()


def test_print_ready_hint_shows_the_prompt_hint() -> None:
    tui = JaegerTUI(skip_model=True)
    tui.console = Console(width=120)
    with tui.console.capture() as cap:
        tui._print_ready_hint()
    assert "Type a prompt" in cap.get()


def test_boot_eager_is_skipped_when_skip_model() -> None:
    """skip_model mode must never trigger a boot, eager or otherwise."""
    tui = JaegerTUI(skip_model=True)
    tui._ensure_agent = MagicMock()
    tui._boot_eager()
    tui._ensure_agent.assert_not_called()


def test_boot_eager_swallows_boot_failure() -> None:
    """A boot error at launch is non-fatal — _boot_eager prints it and
    returns so the REPL can retry on the first turn."""
    tui = JaegerTUI(skip_model=False)
    tui.console = Console(width=120)
    tui._ensure_agent = MagicMock(side_effect=RuntimeError("gemma exploded"))
    with tui.console.capture() as cap:
        tui._boot_eager()  # must not raise
    out = cap.get()
    assert "Boot failed" in out
    assert "gemma exploded" in out


def test_auto_idle_defaults_to_thirty_minutes() -> None:
    """Jaegers use free time — auto-idle Deep Think is on by default."""
    from jaeger_ai.core.instance.schemas import DeepThinkConfig
    assert DeepThinkConfig().auto_idle_minutes == 30
