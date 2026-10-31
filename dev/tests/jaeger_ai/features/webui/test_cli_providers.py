"""Subscription CLIs as compare/model providers: parsing, routing, settings, and never touching credentials."""
from __future__ import annotations

import importlib.util
import io
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/cli_providers.py"


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_cli_providers", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(cli, **over):
    base = {"id": "codex", "label": "OpenAI Codex", "installed": True, "path": "/bin/codex", "signed_in": True, "enabled": True, "login_command": "codex login"}
    return lambda refresh=False: [{**base, **over}]


class _Proc:
    def __init__(self, lines, code=0, err=""):
        self.stdout = io.StringIO("".join(json.dumps(x) + "\n" for x in lines))
        self.stderr = io.StringIO(err)
        self.returncode = code

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass


def test_codex_stream_maps_messages_and_usage(cli, monkeypatch):
    monkeypatch.setattr(cli, "detect", _rows(cli))
    seen = {}
    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return _Proc([{"type": "thread.started"}, {"type": "item.completed", "item": {"type": "error", "message": "warning"}},
                      {"type": "item.completed", "item": {"type": "agent_message", "text": "pong"}},
                      {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 5}}])
    evs = list(cli.stream("codex", "gpt-6-luna", "hi", popen=popen))
    assert [e["type"] for e in evs] == ["start", "delta", "done"]
    assert evs[-1]["eval_count"] == 5 and evs[-1]["prompt_eval_count"] == 100 and evs[-1]["cost_usd"] is None
    assert evs[-1]["tokens_per_s"] is None  # Codex emits whole messages, so no honest tok/s
    assert seen["cmd"][:2] == ["/bin/codex", "exec"] and "read-only" in seen["cmd"] and "--ephemeral" in seen["cmd"]


def test_claude_stream_partial_tokens_and_cost(cli, monkeypatch):
    monkeypatch.setattr(cli, "detect", _rows(cli, id="claude", label="Claude Code", path="/bin/claude"))
    lines = [{"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "po"}}}, {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "ng"}}},
             {"type": "result", "is_error": False, "usage": {"input_tokens": 9, "output_tokens": 2}, "total_cost_usd": 0.0012}]
    evs = list(cli.stream("claude", "sonnet", "hi", popen=lambda cmd, **kw: _Proc(lines)))
    assert "".join(e.get("text", "") for e in evs if e["type"] == "delta") == "pong"
    assert evs[-1]["cost_usd"] == 0.0012 and evs[-1]["eval_count"] == 2


def test_needs_sign_in_and_disabled_never_spawn(cli, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not run")
    monkeypatch.setattr(cli, "detect", _rows(cli, signed_in=False))
    assert "needs sign-in" in list(cli.stream("codex", "m", "hi", popen=boom))[-1]["error"]
    monkeypatch.setattr(cli, "detect", _rows(cli, enabled=False))
    assert "turned off" in list(cli.stream("codex", "m", "hi", popen=boom))[-1]["error"]


def test_failure_reason_comes_from_stderr(cli, monkeypatch):
    monkeypatch.setattr(cli, "detect", _rows(cli, id="gemini", label="Gemini CLI"))
    evs = list(cli.stream("gemini", "auto", "hi", popen=lambda cmd, **kw: _Proc([], code=55, err="x\n  reasonMessage: 'This client is no longer supported',\n")))
    assert evs[-1] == {"type": "error", "error": "Gemini CLI exited 55: This client is no longer supported"}


def test_gemini_signin_checks_file_presence_only(cli, monkeypatch, tmp_path):
    (tmp_path / ".gemini").mkdir()
    creds = tmp_path / ".gemini" / "oauth_creds.json"
    creds.write_text("SECRET")
    monkeypatch.setattr(cli, "HOME", tmp_path)
    real_open = pathlib.Path.read_text
    def guarded(self, *a, **k):
        assert self.name != "oauth_creds.json", "credential file must never be read"
        return real_open(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "read_text", guarded)
    ok, note = cli._gemini_signin("/bin/gemini")
    assert ok is True and "SECRET" not in note


def test_settings_enable_and_models(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_which", lambda b: None)
    cli.update("codex", {"enabled": False, "models": ["gpt-6-luna", "gpt-6-luna"]})
    saved = json.loads((tmp_path / "providers/cli.json").read_text())
    assert saved == {"codex": {"enabled": False, "models": ["gpt-6-luna"]}}
    with pytest.raises(ValueError):
        cli.update("codex", {"models": ["bad model; rm"]})
    with pytest.raises(KeyError):
        cli.update("nope", {})
    row = next(r for r in cli.detect(refresh=True) if r["id"] == "codex")
    assert row["state"] == "not-installed" and row["enabled"] is False
