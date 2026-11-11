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


# ── IDE host LM bridge ──
import http.server
import threading


def _fake_bridge(token, consent="granted", models=("gpt-5.6-luna",), lines=None, host="Visual Studio Code"):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self._json(401, {"error": "unauthorized"})
            if self.path == "/health":
                return self._json(200, {"ok": True, "vscode": host, "host": host, "consent": consent})
            return self._json(200, {"models": [{"id": m, "name": m.upper(), "max_input_tokens": 128000} for m in models]})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n))
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            for ev in (lines or [{"type": "start"}, {"type": "delta", "text": f"hi from {body['model']}"}, {"type": "done", "elapsed_s": 1.2, "ttft_s": 0.4, "eval_count": 4, "prompt_eval_count": 2, "tokens_per_s": 5.0, "source": host}]):
                self.wfile.write((json.dumps(ev) + "\n").encode())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _vs_home(cli, tmp_path, monkeypatch, port=None, token="t" * 64, pid=None, module="host-lm-bridge.js", ext_root=".vscode/extensions"):
    monkeypatch.setattr(cli, "HOME", tmp_path)
    ext = tmp_path / ext_root / "jenkins-robotics.jaeger-ide-0.4.2"
    ext.mkdir(parents=True); (ext / module).write_text("//")
    if port:
        run = tmp_path / ".jaeger/run"; run.mkdir(parents=True)
        (run / "vscode-bridge.json").write_text(json.dumps({"port": port, "token": token, "pid": pid or __import__("os").getpid(), "host": "Visual Studio Code"}))


def test_vscode_states_without_bridge(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HOME", tmp_path)
    assert cli._vscode_row()["bridge"] == "not-installed"
    _vs_home(cli, tmp_path, monkeypatch)
    row = cli._vscode_row()
    assert row["installed"] and row["bridge"] == "not-running" and "IDE not running" in row["status_note"]


def test_vscode_stale_bridge_file_is_not_running(cli, tmp_path, monkeypatch):
    _vs_home(cli, tmp_path, monkeypatch, port=1, pid=999999)
    assert cli._vscode_row()["bridge"] == "not-running"


def test_legacy_copilot_bridge_module_still_counts_as_installed(cli, tmp_path, monkeypatch):
    _vs_home(cli, tmp_path, monkeypatch, module="copilot-bridge.js")
    row = cli._vscode_row()
    assert row["installed"] and row["bridge"] == "not-running"


def test_antigravity_extension_root_is_detected(cli, tmp_path, monkeypatch):
    _vs_home(cli, tmp_path, monkeypatch, ext_root=".antigravity/extensions")
    assert cli._bridge_installed() is True


def test_vscode_ready_lists_copilot_models_and_never_returns_the_token(cli, tmp_path, monkeypatch):
    token = "a" * 64
    srv = _fake_bridge(token)
    try:
        _vs_home(cli, tmp_path, monkeypatch, port=srv.server_address[1], token=token)
        monkeypatch.setattr(cli, "SPECS", {})
        rows = cli.detect(refresh=True)
        row = next(r for r in rows if r["id"] == "vscode")
        assert row["state"] == "ready" and [m["id"] for m in row["models"]] == ["gpt-5.6-luna"]
        assert row["label"] == "IDE Host Models"
        assert token not in json.dumps(rows)
        evs = list(cli.stream("vscode", "gpt-5.6-luna", "hello"))
        assert [e["type"] for e in evs] == ["start", "delta", "done"]
        assert evs[1]["text"] == "hi from gpt-5.6-luna" and evs[-1]["eval_count"] == 4 and evs[-1]["model"] == "cli:vscode:gpt-5.6-luna"
        assert evs[-1]["source"] == "Visual Studio Code"
    finally:
        srv.shutdown()


def test_vscode_consent_and_errors(cli, tmp_path, monkeypatch):
    token = "b" * 64
    srv = _fake_bridge(token, consent="needed", lines=[{"type": "start"}, {"type": "error", "code": "needs_consent", "error": "Run Allow"}])
    try:
        _vs_home(cli, tmp_path, monkeypatch, port=srv.server_address[1], token=token)
        monkeypatch.setattr(cli, "SPECS", {})
        row = next(r for r in cli.detect(refresh=True) if r["id"] == "vscode")
        assert row["state"] == "needs-consent" and "Allow Host Models for Jaeger" in row["status_note"]
        assert "Allow Copilot for Jaeger" in row["status_note"]
        assert list(cli._vscode_stream(row, "gpt-5.6-luna", "hi"))[-1] == {"type": "error", "error": "Host model: Run Allow"}
    finally:
        srv.shutdown()


def test_vscode_wrong_token_is_not_running(cli, tmp_path, monkeypatch):
    srv = _fake_bridge("c" * 64)
    try:
        _vs_home(cli, tmp_path, monkeypatch, port=srv.server_address[1], token="d" * 64)
        assert cli._vscode_row()["bridge"] == "not-running"
    finally:
        srv.shutdown()
