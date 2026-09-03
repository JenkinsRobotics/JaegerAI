"""CliBackendAdapter — flatten, parse, no live CLI."""

from __future__ import annotations

import json
from types import SimpleNamespace

from jaeger_agent.adapters.cli_backend import (
    CliBackendAdapter,
    flatten_messages,
    parse_cli_text,
)
from jaeger_agent.schemas.message_types import Message
from jaeger_os.core.tools.tool_schema import ToolDef


def test_flatten_messages_joins_system_and_transcript():
    prompt = flatten_messages(
        [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="user", content="status?"),
        ],
        [],
        "you are jaeger",
    )
    assert "System:\nyou are jaeger" in prompt
    assert "User:\nhi" in prompt
    assert "Assistant:\nhello" in prompt
    assert "User:\nstatus?" in prompt


def test_flatten_mentions_jaeger_tools():
    from pydantic import BaseModel

    class _Args(BaseModel):
        pass

    tool = ToolDef(
        name="get_time",
        description="now",
        args_model=_Args,
        fn=lambda: "ok",
    )
    prompt = flatten_messages(
        [Message(role="user", content="what time")],
        [tool],
        "",
    )
    assert "get_time" in prompt
    assert "Jaeger owns tools" in prompt


def test_parse_json_stdout_extracts_result():
    raw = json.dumps({"type": "result", "result": "the sky is blue"})
    adapter = CliBackendAdapter("claude", executable="/bin/true")
    msg = adapter.parse_response({"stdout": raw, "stderr": "", "returncode": 0})
    assert msg["role"] == "assistant"
    assert msg["content"] == "the sky is blue"


def test_parse_nested_content_and_ndjson():
    blob = (
        json.dumps({"type": "item", "text": "ignored"})
        + "\n"
        + json.dumps({"message": {"content": "final answer"}})
        + "\n"
    )
    assert parse_cli_text(blob) == "final answer"


def test_parse_falls_back_to_raw_stdout():
    adapter = CliBackendAdapter("hermes", executable="/bin/true")
    msg = adapter.parse_response({"stdout": "plain text reply\n", "stderr": ""})
    assert msg["content"] == "plain text reply"


def test_format_messages_returns_prompt_payload():
    adapter = CliBackendAdapter("codex", executable="/bin/true")
    formatted = adapter.format_messages(
        [Message(role="user", content="ping")],
        [],
        "sys",
    )
    assert formatted["prompt"].startswith("System:\nsys")
    assert "User:\nping" in formatted["prompt"]


def test_health_check_missing_binary(monkeypatch):
    adapter = CliBackendAdapter("claude")

    def boom(_backend_id):
        raise RuntimeError("CLI backend 'claude' is not installed on PATH")

    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.get_spec",
        boom,
    )
    result = adapter.health_check()
    assert result["ok"] is False
    assert "not installed" in result["detail"]


def test_spawn_uses_argv_and_env_allowlist(monkeypatch):
    """No shell, no leaked env. Stdin backends pass the prompt as bytes."""
    adapter = CliBackendAdapter("claude", executable="/opt/homebrew/bin/claude")
    spec = SimpleNamespace(
        args=("--print", "--output-format", "json"),
        prompt_mode="stdin",
        credential_env=("ANTHROPIC_API_KEY",),
        probe_args=("--version",),
        executables=("claude",),
        id="claude",
    )
    captured: dict = {}

    class _Proc:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.returncode = 0
            self.pid = 4242

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            captured["timeout"] = timeout
            return b'{"result": "ok"}', b""

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(
        "jaeger_agent.adapters.cli_backend.subprocess.Popen", _Proc,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-leak")
    raw = adapter._spawn(
        ["/opt/homebrew/bin/claude", "--print", "--output-format", "json"],
        b"hello",
        spec,
    )
    assert captured["shell"] is False
    assert captured["args"][0] == "/opt/homebrew/bin/claude"
    assert captured["input"] == b"hello"
    env = captured["env"]
    assert env["ANTHROPIC_API_KEY"] == "sk-secret"
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert json.loads(raw["stdout"])["result"] == "ok"
