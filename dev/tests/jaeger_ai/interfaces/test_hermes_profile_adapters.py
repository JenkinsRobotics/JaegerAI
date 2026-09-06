from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
import json

from jaeger_ai.interfaces.hermes_profile_adapters import roundtable
from jaeger_ai.interfaces.hermes_profile_adapters import jaeger
from jaeger_ai.interfaces.hermes_profile_adapters import setup


def test_runs_protocol_matches_webui_and_closes_connection():
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from jaeger_ai.interfaces.hermes_profile_adapters import openclaw

    # Jaeger's durable/native Runs API is exercised by test_native_runs.py;
    # these two adapters still support their legacy in-memory run records.
    for module, handler_type in ((roundtable, roundtable.RoundtableHandler),
                                 (openclaw, openclaw.Handler)):
        run_id = "protocol-test"
        with module._runs_lock:
            module._runs[run_id] = {"status": "completed", "result": "READY", "error": ""}
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/v1/runs/{run_id}/events", timeout=2) as response:
                text = response.read().decode()  # Must reach EOF, not hang until timeout.
            events = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
            assert events[0] == {"event": "message.delta", "delta": "READY"}
            assert events[-1]["event"] == "run.completed"
        finally:
            server.shutdown()
            server.server_close()
            with module._runs_lock:
                module._runs.pop(run_id, None)


def test_incident_discussion_does_not_crash(monkeypatch):
    for name in ("chat_hermes", "chat_jaeger", "chat_openclaw"):
        monkeypatch.setattr(roundtable, name, lambda *args: "[Unknown] Need evidence")
    chunks = []
    roundtable.run_debate_stream("/incident diagnose service errors", chunks.append, "incident-test")
    assert "Decision Summary" in "".join(chunks)


def test_failed_member_is_not_asked_to_discuss(monkeypatch):
    calls = []
    monkeypatch.setattr(roundtable, "chat_hermes", lambda *args: calls.append("hermes") or "LLM request timed out.")
    monkeypatch.setattr(roundtable, "chat_jaeger", lambda *args: "Ready")
    monkeypatch.setattr(roundtable, "chat_openclaw", lambda *args: "Ready")
    roundtable.run_debate_stream("hello", lambda text: None, "failure-test")
    assert calls == ["hermes"]


def test_roundtable_streams_group_chat_and_consensus(monkeypatch):
    monkeypatch.setattr(roundtable, "chat_hermes", lambda prompt, session_id="": "Hermes answer")
    monkeypatch.setattr(roundtable, "chat_jaeger", lambda prompt, session_id="": "Jaeger answer")
    monkeypatch.setattr(roundtable, "chat_openclaw", lambda prompt, session_id="": "OpenClaw answer")
    chunks = []

    roundtable.run_debate_stream("Question?", chunks.append)
    output = "".join(chunks)

    assert "Round 1 — Everyone Answers" in output
    assert "Round 2 — Group Discussion" in output
    assert "Hermes answer" in output
    assert "Jaeger answer" in output
    assert "OpenClaw answer" in output
    assert "## 🤝 Decision Summary" in output
    assert "**Chair:**" in output


def test_chat_adapter_does_not_replay_ambiguous_remote_disconnect(monkeypatch):
    from http.client import RemoteDisconnected

    calls = {"n": 0}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            chunk = {
                "id": "1",
                "choices": [{"index": 0, "delta": {"content": "recovered"}}],
            }
            yield f"data: {json.dumps(chunk)}\n".encode()
            yield b"data: [DONE]\n"

    def urlopen(_request, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RemoteDisconnected("Remote end closed connection without response")
        return FakeResp()

    monkeypatch.setattr(roundtable.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(roundtable.time, "sleep", lambda _seconds: None)

    assert roundtable._is_failed_answer(roundtable.chat_jaeger("hi", "session-1"))
    assert calls["n"] == 1


def test_jaeger_chat_returns_json_when_body_is_invalid():
    handler = object.__new__(jaeger.RunHandler)
    handler.headers = {"Content-Length": "3"}
    handler.rfile = BytesIO(b"{no")
    captured = {}
    handler._send_json = lambda status, payload: captured.update(status=status, payload=payload)

    handler._handle_chat_completions()

    assert captured["status"] == 500
    assert "error" in captured["payload"]


def test_jaeger_chat_uses_a_fresh_mcp_session_per_turn(monkeypatch):
    created = []
    host = jaeger.MCPClient("http://127.0.0.1:8811/mcp", "key", "127.0.0.1:8811")

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            created.append(self)
            self.calls = []

        def initialize(self):
            self.calls.append("initialize")
            return {}

        def _execute_call(self, name, arguments):
            self.calls.append((name, arguments))
            return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(jaeger, "MCPClient", FakeWorker)

    result = host.chat("hello", "table-1")

    assert result["content"][0]["text"] == "ok"
    assert len(created) == 1
    assert created[0].calls == ["initialize", ("chat", {"message": "hello", "session_id": "table-1"})]


def test_jaeger_nonstream_completion_returns_openai_json(monkeypatch):
    monkeypatch.setattr(
        jaeger.mcp_client,
        "chat",
        lambda _message, _session_id=None: {
            "content": [{"type": "text", "text": "READY"}],
        },
    )
    handler = object.__new__(jaeger.RunHandler)
    body = json.dumps({
        "stream": False,
        "messages": [{"role": "user", "content": "test"}],
    }).encode()
    handler.headers = {
        "Content-Length": str(len(body)),
        "X-Hermes-Session-Id": "session-1",
    }
    from io import BytesIO
    handler.rfile = BytesIO(body)
    captured = {}
    handler._send_json = lambda status, payload: captured.update(status=status, payload=payload)

    handler._handle_chat_completions()

    assert captured["status"] == 200
    assert captured["payload"]["object"] == "chat.completion"
    assert captured["payload"]["choices"][0]["message"]["content"] == "READY"


def test_jaeger_runtime_artifacts_live_inside_repository():
    assert setup.JAEGER_RUNTIME_ROOT == setup.REPO_ROOT / ".jaeger_ai" / "shared"
    plist = setup._plist("test.adapter", "example.module")
    assert str(setup.JAEGER_RUNTIME_ROOT / "logs").encode() in plist


def test_roundtable_keeps_other_members_when_one_fails(monkeypatch):
    monkeypatch.setattr(roundtable, "chat_hermes", lambda prompt, session_id="": "Hermes answer")
    monkeypatch.setattr(roundtable, "chat_jaeger", lambda prompt, session_id="": "Jaeger answer")

    def fail(_prompt, session_id=""):
        raise RuntimeError("offline")

    monkeypatch.setattr(roundtable, "chat_openclaw", fail)
    chunks = []

    roundtable.run_debate_stream("Question?", chunks.append)
    output = "".join(chunks)

    assert "Hermes answer" in output
    assert "Jaeger answer" in output
    assert "OpenClaw" in output
    assert "offline" in output
    assert "## 🤝 Decision Summary" in output


def test_member_session_ids_are_stable_and_isolated():
    first = roundtable._member_session_id("table-1", "jaeger")
    assert first == roundtable._member_session_id("table-1", "jaeger")
    assert first != roundtable._member_session_id("table-1", "openclaw")
    assert first != roundtable._member_session_id("table-2", "jaeger")


def test_hermes_uses_same_native_named_session_on_separate_turns(monkeypatch):
    monkeypatch.setattr(roundtable.shutil, "which", lambda _name: "/bin/hermes")
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=f"answer {len(commands)}\n",
        )

    monkeypatch.setattr(roundtable.subprocess, "run", run)

    assert roundtable.chat_hermes("first", "table-1") == "answer 1"
    assert roundtable.chat_hermes("second", "table-1") == "answer 2"
    assert commands[0][1:3] == ["chat", "-c"]
    assert commands[0][3] == commands[1][3]
    assert "--create-if-missing" in commands[0]
    assert commands[0][-3:] == ["first", "--source", "tool"]
    assert commands[1][-3:] == ["second", "--source", "tool"]


def test_turn_plan_defaults_to_all_and_supports_mentions():
    default = roundtable._turn_plan("What should we build?")
    assert default["mode"] == "ask"
    assert default["participants"] == roundtable.AGENT_ORDER

    selected = roundtable._turn_plan("/review @jaeger @openclaw inspect this proposal")
    assert selected["mode"] == "review"
    assert selected["participants"] == ("jaeger", "openclaw")


def test_operational_turn_requires_evidence_labels():
    plan = roundtable._turn_plan("Collaborate to diagnose the broken container service")
    assert plan["mode"] == "collaborate"
    assert plan["evidence_required"] is True
    prompt = roundtable._member_prompt(plan, "jaeger")
    assert "[Verified]" in prompt
    assert "Never translate a timeout into 'service down'" in prompt
    assert "historical artifacts, not deployed source" in prompt


def test_quick_mode_selects_one_best_member(monkeypatch):
    calls = []
    monkeypatch.setattr(roundtable, "chat_hermes", lambda prompt, session_id="": calls.append("hermes") or "answer")
    monkeypatch.setattr(roundtable, "chat_jaeger", lambda prompt, session_id="": calls.append("jaeger") or "answer")
    monkeypatch.setattr(roundtable, "chat_openclaw", lambda prompt, session_id="": calls.append("openclaw") or "answer")
    chunks = []

    roundtable.run_debate_stream("/quick diagnose the container", chunks.append)

    assert calls == ["hermes"]
    assert "Round 2" not in "".join(chunks)


def test_setup_adds_shared_workspace_roots_without_erasing_existing_grants(tmp_path):
    grants = tmp_path / ".ares" / "capabilities" / "grants.json"
    grants.parent.mkdir(parents=True)
    grants.write_text(json.dumps({
        "version": 1,
        "identities": {
            "hermes": {"roots": ["/existing/hermes"], "capabilities": ["workspace.read"]},
            "jaeger": {"roots": [], "capabilities": ["workspace.write"]},
        },
    }))

    assert setup._configure_workspace_roots(tmp_path) == grants
    document = json.loads(grants.read_text())

    expected = {
        str(tmp_path / "workspace"),
        str(tmp_path / "GitHub"),
        str(tmp_path / "Desktop"),
        str(tmp_path / "Documents"),
        "/Volumes/Jenkins_Robotics",
        "/Volumes/Personal-Drive",
    }
    for identity in setup.WORKSPACE_IDENTITIES:
        assert expected <= set(document["identities"][identity]["roots"])
    assert "/existing/hermes" in document["identities"]["hermes"]["roots"]
    assert document["identities"]["hermes"]["capabilities"] == ["workspace.read"]
    assert document["identities"]["jaeger"]["capabilities"] == ["workspace.write"]


def test_setup_publishes_same_workspace_tab_catalog_for_every_profile(tmp_path):
    paths = setup._configure_webui_workspaces(tmp_path)

    assert len(paths) == 4
    expected = [
        {"path": path, "name": name}
        for path, name in setup.WEBUI_WORKSPACES
    ]
    for path in paths:
        assert json.loads(path.read_text(encoding="utf-8")) == expected


def test_setup_configures_native_and_profile_model_defaults(tmp_path):
    for profile in setup.SERVICES:
        path = tmp_path / ".hermes" / "profiles" / profile / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("model:\n  default: old:cloud\n  provider: ollama\n")
    hermes_default = tmp_path / ".hermes" / "config.yaml"
    hermes_default.write_text("model:\n  default: old:cloud\n  provider: ollama\n")
    jaeger = tmp_path / ".jaeger_ai" / "instances" / "jaeger" / "config.yaml"
    jaeger.parent.mkdir(parents=True)
    jaeger.write_text("external_model:\n  enabled: true\n  model: old:cloud\n")
    openclaw = tmp_path / ".ares" / "openclaw" / "openclaw.json"
    openclaw.parent.mkdir(parents=True)
    openclaw.write_text(json.dumps({"agents": {"defaults": {"model": {"primary": "old/model"}}}, "models": {"providers": {"ollama-cloud-via-host": {"models": []}}}}))

    setup._configure_agent_models(tmp_path)

    for profile in setup.SERVICES:
        assert f"default: {setup.DEFAULT_AGENT_MODEL}" in (
            tmp_path / ".hermes" / "profiles" / profile / "config.yaml"
        ).read_text()
    assert f"default: {setup.DEFAULT_AGENT_MODEL}" in hermes_default.read_text()
    assert f"model: {setup.DEFAULT_AGENT_MODEL}" in jaeger.read_text()
    assert f"base_url: {setup.DEFAULT_OLLAMA_BASE_URL}" in jaeger.read_text()
    config = json.loads(openclaw.read_text())
    assert config["agents"]["defaults"]["model"]["primary"].endswith(setup.DEFAULT_AGENT_MODEL)
    assert config["models"]["providers"]["ollama-cloud-via-host"]["models"][0]["id"] == setup.DEFAULT_AGENT_MODEL
    assert any(
        model["id"] == "glm-5.3:cloud"
        for model in config["models"]["providers"]["ollama-cloud-via-host"]["models"]
    )
    assert config["agents"]["defaults"]["memorySearch"] == {
        "provider": "ollama",
        "model": setup.OPENCLAW_EMBEDDING_MODEL,
        "remote": {"baseUrl": "http://10.15.0.239:11434"},
    }


def test_setup_connects_every_profile_and_openclaw_to_jaeger_mcp(tmp_path):
    for profile_home in [tmp_path / ".hermes"] + [
        tmp_path / ".hermes" / "profiles" / profile for profile in setup.SERVICES
    ]:
        profile_home.mkdir(parents=True, exist_ok=True)
        profile_home.joinpath("config.yaml").write_text("model:\n  default: test\n")
    openclaw = tmp_path / ".ares" / "openclaw" / "openclaw.json"
    openclaw.parent.mkdir(parents=True)
    openclaw.write_text("{}")

    setup._configure_agent_connectivity(tmp_path)

    for profile_home in [tmp_path / ".hermes"] + [
        tmp_path / ".hermes" / "profiles" / profile for profile in setup.SERVICES
    ]:
        config = profile_home.joinpath("config.yaml").read_text()
        assert "jaeger-host:" in config
        assert setup.JAEGER_MCP_URL in config
    document = json.loads(openclaw.read_text())
    assert document["mcp"]["servers"]["jaeger-host"]["url"].endswith(":8811/mcp")


def test_setup_configures_profile_isolated_honcho_peers_on_lan(tmp_path):
    paths = setup._configure_honcho(tmp_path)

    assert len(paths) == 4
    for path in paths:
        document = json.loads(path.read_text())
        assert document["baseUrl"] == "http://10.15.0.239:8088"
        block = next(iter(document["hosts"].values()))
        assert block["workspace"] == "jenkins-robotics"
        assert block["enabled"] is True
        assert "provider: honcho" in path.with_name("config.yaml").read_text()
