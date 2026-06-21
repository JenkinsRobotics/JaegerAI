"""TUI port — the new session-info slash commands.

`/status` `/statusbar` `/stop` `/save` were added in the prompt_toolkit
TUI port. The interactive input layer needs a real terminal, but these
command handlers are testable against a model-less JaegerTUI.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from jaeger_os.interfaces.tui import slash_commands as slash
from jaeger_os.interfaces.tui.app import JaegerTUI


@pytest.fixture()
def ctx(tmp_path):
    tui = JaegerTUI(skip_model=True)
    return slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=100),
        instance_dir=tmp_path,
        tui=tui,
    )


def test_new_commands_are_registered() -> None:
    for name in ("status", "statusbar", "stop", "save"):
        assert name in slash._BY_NAME, name


def test_statusbar_toggles_the_flag(ctx) -> None:
    ctx.tui._statusbar_on = True
    slash.dispatch("/statusbar", ctx)
    assert ctx.tui._statusbar_on is False
    slash.dispatch("/statusbar", ctx)
    assert ctx.tui._statusbar_on is True


def test_status_runs_clean(ctx) -> None:
    assert slash.dispatch("/status", ctx).quit is False


def test_stop_runs_clean_with_no_processes(ctx) -> None:
    # No tools bound / no processes — must not raise, just report.
    assert slash.dispatch("/stop", ctx).quit is False


def test_save_runs_clean(ctx) -> None:
    # Empty conversation — must not raise.
    assert slash.dispatch("/save", ctx).quit is False


# ── /model use <cloud provider> ──────────────────────────────────────


def test_cloud_provider_maps_are_consistent() -> None:
    """Every cloud provider must carry a base URL, a credential name, a
    key hint and an example model — so /model use <provider> never
    half-works for one of them."""
    for prov in slash._CLOUD_PROVIDERS:
        assert prov in slash._CLOUD_BASE_URL, prov
        assert prov in slash._CLOUD_CRED, prov
        assert prov in slash._CLOUD_KEY_HINT, prov
        assert prov in slash._CLOUD_EXAMPLE, prov
    # Each provider keeps its key under its OWN credential name — a
    # collision would mean switching providers clobbers a stored key.
    assert len(set(slash._CLOUD_CRED.values())) == len(slash._CLOUD_CRED)


def test_cloud_providers_are_valid_schema_providers() -> None:
    """The TUI's cloud list must stay in sync with the config schema's
    accepted providers."""
    from jaeger_os.core.instance.schemas import ExternalModelConfig
    for prov in slash._CLOUD_PROVIDERS:
        assert ExternalModelConfig(provider=prov, model="x").provider == prov


def test_gemini_uses_openai_compatible_endpoint() -> None:
    """Gemini must point at Google's OpenAI-compatible surface so it
    rides external_model's openai path — no native adapter."""
    url = slash._CLOUD_BASE_URL["gemini"]
    assert "generativelanguage.googleapis.com" in url
    assert "openai" in url


def test_cloud_aliases_resolve_to_real_providers() -> None:
    """Every alias must resolve to a provider in _CLOUD_PROVIDERS."""
    for alias, prov in slash._CLOUD_ALIASES.items():
        assert prov in slash._CLOUD_PROVIDERS, alias


# ── permission confirmation — the hermes-pattern fix ────────────────
# Regression cover for the bug where a tier-gated tool's confirmation
# ran a worker-thread `console.input()` that never captured the user's
# answer — so every browser / run_shell / computer_use call auto-denied.
# The fix: the worker blocks on an Event; the REPL routes the typed line.


def test_pending_confirm_resolve_is_false_when_nothing_waits() -> None:
    tui = JaegerTUI(skip_model=True)
    assert tui._resolve_pending_confirm("y") is False


def test_pending_confirm_routes_the_answer_and_wakes_the_worker() -> None:
    import threading
    tui = JaegerTUI(skip_model=True)
    box = {"event": threading.Event(), "answer": None}
    tui._pending_confirm = box
    assert tui._resolve_pending_confirm("always") is True
    assert box["answer"] == "always"
    assert box["event"].is_set()


@pytest.mark.parametrize("answer,expected", [
    ("a", True), ("always", True), ("y", True), ("yes", True),
    ("n", False), ("no", False), ("", False), ("nonsense", False),
])
def test_confirmation_roundtrip(monkeypatch, tmp_path, answer, expected) -> None:
    """The worker blocks in confirm(); the REPL routes the typed answer
    back and wakes it — the hermes approval-pipeline pattern."""
    import os
    import sys
    import threading
    import time

    from jaeger_os.core.safety.permissions import PermissionRequest, PermissionTier
    from jaeger_os.interfaces.tui.app import _TuiConfirmationProvider

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    tui = JaegerTUI(instance_dir=tmp_path, skip_model=True)
    tui.console = Console(file=open(os.devnull, "w"), width=100)
    prov = _TuiConfirmationProvider(tui)
    req = PermissionRequest(
        tier=PermissionTier.EXTERNAL_EFFECT, skill="browser",
        operation="browser", summary="drive a real web browser")

    result: dict = {}
    worker = threading.Thread(target=lambda: result.__setitem__(
        "ok", prov.confirm(req)))
    worker.start()
    # Wait for the worker to post the pending confirmation.
    for _ in range(300):
        if tui._pending_confirm is not None:
            break
        time.sleep(0.01)
    assert tui._pending_confirm is not None, "prompt never posted"
    assert tui._resolve_pending_confirm(answer) is True
    worker.join(timeout=5)
    assert worker.is_alive() is False
    assert result["ok"] is expected


def test_confirmation_denies_on_non_interactive_stdin(monkeypatch) -> None:
    """Piped / non-tty stdin — no live user; fail safe, never block."""
    import sys

    from jaeger_os.core.safety.permissions import PermissionRequest, PermissionTier
    from jaeger_os.interfaces.tui.app import _TuiConfirmationProvider

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    prov = _TuiConfirmationProvider(JaegerTUI(skip_model=True))
    req = PermissionRequest(
        tier=PermissionTier.EXTERNAL_EFFECT, skill="browser",
        operation="browser")
    assert prov.confirm(req) is False


# ── /peek — look into a running turn ────────────────────────────────


def _peek_output(monkeypatch, *, turn_running: bool, progress) -> str:
    import io

    from jaeger_os.main import _pipeline

    tui = JaegerTUI(skip_model=True)
    buf = io.StringIO()
    tui.console = Console(file=buf, width=100)
    if turn_running:
        tui._turn_running.set()
    monkeypatch.setitem(_pipeline, "turn_progress", progress)
    sctx = slash.SlashContext(console=tui.console,
                              instance_dir=tui.instance_dir, tui=tui)
    slash.dispatch("/peek", sctx)
    return buf.getvalue()


def test_peek_is_registered_and_turn_safe() -> None:
    from jaeger_os.interfaces.tui.app import _TURN_UNSAFE_SLASH
    assert "peek" in slash._BY_NAME
    assert "peek" not in _TURN_UNSAFE_SLASH   # must run DURING a turn


def test_peek_with_no_turn_running(monkeypatch) -> None:
    out = _peek_output(monkeypatch, turn_running=False, progress=None)
    assert "No turn is running" in out


def test_peek_while_still_thinking(monkeypatch) -> None:
    out = _peek_output(monkeypatch, turn_running=True, progress=None)
    assert "thinking" in out


def test_peek_reports_a_healthy_turn(monkeypatch) -> None:
    out = _peek_output(monkeypatch, turn_running=True, progress={
        "active": True, "elapsed_s": 42.0, "tool_calls": 4,
        "last_tool": "read_file", "phase": "done",
        "repeated_max": 1, "repeated_tool": "read_file", "failures": 0,
    })
    assert "looks healthy" in out
    assert "4 tool calls" in out


def test_peek_flags_a_loop(monkeypatch) -> None:
    out = _peek_output(monkeypatch, turn_running=True, progress={
        "active": True, "elapsed_s": 300.0, "tool_calls": 18,
        "last_tool": "web_fetch", "phase": "start",
        "repeated_max": 6, "repeated_tool": "web_fetch", "failures": 1,
    })
    assert "possible loop" in out
    assert "web_fetch" in out
    assert "looks healthy" not in out


# ── _tool_label — legible computer-use activity lines ───────────────


def test_tool_label_tags_computer_use_with_platform_and_mode() -> None:
    from jaeger_os.interfaces.tui.app import _tool_label

    fg = _tool_label("computer_windows")
    assert "macOS" in fg and "foreground" in fg and "windows" in fg

    bg = _tool_label("computer_bg_move")
    assert "macOS" in bg and "background" in bg and "move" in bg


def test_tool_label_leaves_other_tools_unchanged() -> None:
    from jaeger_os.interfaces.tui.app import _tool_label

    assert _tool_label("read_file") == "read_file"
    assert _tool_label("web_search") == "web_search"


# ── /model use mlx — backend switching ──────────────────────────────


def _wire_model_switch(ctx, monkeypatch):
    """Stub the heavy edges of ``/model use``: discovery, yaml persist,
    and the instance reboot. Returns (cfg, reboots) for assertions."""
    from jaeger_os.core.instance import schemas as schemas_mod
    from jaeger_os.core.models import model_discovery as disc_mod
    import jaeger_os.main as main_mod

    cfg = schemas_mod.Config(
        instance_name="test",
        model=schemas_mod.ModelConfig(model_path="/models/old.gguf"),
    )
    monkeypatch.setitem(main_mod._pipeline, "config", cfg)
    monkeypatch.setattr(
        disc_mod, "discover_local_mlx",
        lambda: [{
            "name": "Qwen3.5-9B-MLX-4bit",
            "path": "/models/mlx/Qwen3.5-9B-MLX-4bit",
            "size_gb": 5.1, "source": "lm studio",
        }],
    )
    monkeypatch.setattr(schemas_mod, "dump_yaml", lambda path, c: None)
    reboots: list[str] = []
    monkeypatch.setattr(ctx.tui, "switch_instance", reboots.append)
    return cfg, reboots


def test_model_use_mlx_switches_backend(ctx, monkeypatch) -> None:
    slash_mod = slash
    cfg, reboots = _wire_model_switch(ctx, monkeypatch)
    slash_mod.dispatch("/model use mlx Qwen3.5-9B-MLX-4bit", ctx)
    assert cfg.model.backend == "mlx_lm"
    assert cfg.model.model_path == "/models/mlx/Qwen3.5-9B-MLX-4bit"
    assert cfg.external_model.enabled is False
    assert reboots  # the brain reboot was requested


def test_model_use_mlx_single_model_autoselects(ctx, monkeypatch) -> None:
    cfg, reboots = _wire_model_switch(ctx, monkeypatch)
    slash.dispatch("/model use mlx", ctx)  # no name — one candidate
    assert cfg.model.backend == "mlx_lm"
    assert cfg.model.model_path.endswith("Qwen3.5-9B-MLX-4bit")
    assert reboots


def test_model_use_local_resets_backend_from_mlx(ctx, monkeypatch) -> None:
    cfg, reboots = _wire_model_switch(ctx, monkeypatch)
    cfg.model.backend = "mlx_lm"  # previously on MLX
    slash.dispatch("/model use local", ctx)
    # Without the reset, ``backend: mlx_lm`` pointed at a .gguf fails
    # to load on the next boot.
    assert cfg.model.backend == "llama_cpp_python"
    assert reboots
