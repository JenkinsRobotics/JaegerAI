from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.features.agent_bridge import engine_worker as w


def task(engine):
    return {"id": "handoff-1", "thread": "t1", "to": engine, "from": "grokbot",
            "kind": "task", "body": "summarize", "created_at": 9e12}


def test_worker_outbox_retry_and_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "workspace", lambda engine: tmp_path / engine)
    state_path = tmp_path / "state.json"
    state = {"after": 0, "since": 0, "done": []}
    runs, sent = [], []
    monkeypatch.setattr(w, "pending", lambda engine, state: [task(engine)] if "handoff-1" not in state["done"] else [])
    monkeypatch.setattr(w, "run_job", lambda engine, m: runs.append(m["id"]) or
                        {"status": "done", "body": "ok", "refs": []})
    monkeypatch.setattr(w, "device_ok", lambda: ["busy"])
    monkeypatch.setattr(w, "call", lambda *args: sent.append(args) or {})
    assert w.tick("hermes", state, state_path) == 0 and not runs
    monkeypatch.setattr(w, "device_ok", lambda: [])
    def fail(*args):
        raise OSError("hub down")
    monkeypatch.setattr(w, "call", fail)
    assert w.tick("hermes", state, state_path) == 1 and runs == ["handoff-1"]
    outbox = w.outbox_path("hermes", "handoff-1")
    assert outbox.exists()
    monkeypatch.setattr(w, "call", lambda *args: sent.append(args) or {})
    assert w.tick("hermes", state, state_path) == 0 and not outbox.exists()
    assert runs == ["handoff-1"]
    assert sent[0][2]["id"] == "hermes-result-" + __import__("hashlib").sha256(b"handoff-1").hexdigest()


def test_engine_commands_and_caller_ceiling(tmp_path):
    cmd = w.command("hermes", "task", tmp_path)
    assert cmd[1:4] == ["chat", "-Q", "--oneshot"] and "--query-file" in cmd
    cmd = w.command("openclaw", "task", tmp_path)
    assert cmd[1:3] == ["agent", "--local"] and "--message-file" in cmd and "--deliver" not in cmd
    spec = caller_auth.CALLERS["hermes"]
    assert spec.session_prefix == "hermes:" and spec.scopes == {"read", "turn"}
    assert caller_auth.prefixed_route_allowed("POST", "/v1/agent-messages", "hermes")
    assert not caller_auth.prefixed_route_allowed("POST", "/v1/agent-goals", "hermes")
    assert not caller_auth.prefixed_route_allowed("GET", "/v1/activity", "hermes")
    # OpenClaw keeps its existing app credential (read/turn/handoff/search), never approve/admin.
    oc = caller_auth.CALLERS["openclaw"]
    assert {"read", "turn"} <= oc.scopes and not ({"approve", "admin", "delegate"} & oc.scopes)


def test_engine_env_strips_keys_and_points_at_jaeger_state(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    env = w.engine_env("hermes")
    assert "OPENAI_API_KEY" not in env and env["HERMES_HOME"].endswith(".jaeger/hermes")
    env = w.engine_env("openclaw")
    assert env["OPENCLAW_CONFIG_PATH"].endswith("openclaw-host/openclaw.json")


def test_final_text_parsing():
    out = "Preparing the isolated Hermes runtime\u2026\n  \u2192 Installing Python dependencies\u2026\nHERMES-OK 42\n\nsession_id: local-1\n"
    assert w.final_text("hermes", out) == "HERMES-OK 42"
    oc = 'migrations...\n{"payloads":[{"text":"OPENCLAW-OK 42"}],"meta":{"finalAssistantVisibleText":"OPENCLAW-OK 42"}}\n{"x":1}'
    assert w.final_text("openclaw", oc) == "OPENCLAW-OK 42"
    assert w.final_text("openclaw", '{"ok":false,"error":{"message":"bad config"}}').startswith("OpenClaw error")
