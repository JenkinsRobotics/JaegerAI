"""``jaeger backends`` lists installed vs missing CLI brains."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from types import SimpleNamespace

from jaeger_ai.cli import backends_cmd
from jaeger_ai.features.cli_backends.discovery import BackendSpec


def test_backends_cmd_prints_installed_and_missing(monkeypatch):
    specs = [
        SimpleNamespace(
            spec=BackendSpec(
                id="claude", executables=("claude",), args=(),
                prompt_mode="stdin", display_name="Claude Code",
            ),
            executable="/opt/homebrew/bin/claude",
            installed=True,
        ),
        SimpleNamespace(
            spec=BackendSpec(
                id="codex", executables=("codex",), args=(),
                prompt_mode="stdin", display_name="Codex CLI",
            ),
            executable=None,
            installed=False,
        ),
    ]
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.service.list_all",
        lambda: specs,
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = backends_cmd.run_backends(SimpleNamespace())
    out = buf.getvalue()
    assert code == 0
    assert "cli:claude" in out
    assert "installed on PATH" in out
    assert "cli:codex" in out
    assert "missing" in out
    assert "Delegates remain workers" in out or "delegate_task" in out
def test_backends_list_verb_is_registered():
    import argparse
    from jaeger_ai.cli import backends_cmd
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="subcommand")
    backends_cmd.register(sub)
    listed = parser.parse_args(["backends", "list"])
    assert listed._handler is backends_cmd.run_backends
    bare = parser.parse_args(["backends"])
    assert bare._handler is backends_cmd.run_backends
