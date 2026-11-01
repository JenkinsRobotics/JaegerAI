from jaeger_ai.core.gateway import caller_auth as ca
from jaeger_ai.features.agent_bridge import rackpc_worker as w


def _setup(tmp_path, monkeypatch, msgs):
    monkeypatch.setattr(w, "WORKDIR", tmp_path)
    posted = []

    def fake_call(tool, args):
        if tool == "receipts":
            return {"messages": msgs if args["after"] == 0 else [], "next_after": None}
        posted.append((tool, args))
        return {}
    monkeypatch.setattr(w, "call", fake_call)
    return posted


def task(i, **kw):
    return {"id": i, "thread": "t1", "to": "rackpc", "kind": "task", "from": "grokbot",
            "body": "say PONG", "created_at": 9e12, **kw}


def test_runs_once_and_posts_result(tmp_path, monkeypatch):
    msgs = [task("h1"), task("h2", kind="status"), task("h3", **{"from": "rackpc"}), task("h4", to="ares")]
    posted = _setup(tmp_path, monkeypatch, msgs)
    ran = []
    monkeypatch.setattr(w, "run_job", lambda m: ran.append(m["id"]) or {"status": "done", "body": "PONG", "elapsed_s": 1})
    assert w.tick(w.State(tmp_path / "state.json")) == 1 and ran == ["h1"]
    tool, args = posted[0]
    assert tool == "send_message" and args["to"] == "grokbot" and args["reply_to"] == "h1"
    assert args["title"] == "Rack PC result"
    assert w.tick(w.State(tmp_path / "state.json")) == 0  # never twice


def test_crash_is_reported_not_rerun(tmp_path, monkeypatch):
    posted = _setup(tmp_path, monkeypatch, [task("h1")])
    monkeypatch.setattr(w, "run_job", lambda m: (_ for _ in ()).throw(RuntimeError("boom")))
    w.tick(w.State(tmp_path / "state.json"))
    assert "error" in posted[0][1]["title"]
    assert w.tick(w.State(tmp_path / "state.json")) == 0


def test_model_line_and_ollama_call(monkeypatch):
    assert w.parse_task("model: llama3.1:8b\nhi") == ("llama3.1:8b", "hi")
    assert w.parse_task("hi") == (w.DEFAULT_MODEL, "hi")
    seen = {}

    def fake(path, payload=None, timeout=10):
        seen.update(path=path, model=payload["model"])
        return {"message": {"content": "PONG"}, "eval_count": 2, "eval_duration": 1e8}
    monkeypatch.setattr(w, "_ollama", fake)
    out = w.run_job(task("h1", body="model: qwen3:4b\nsay PONG"))
    assert out["status"] == "done" and out["body"].startswith("PONG")
    assert seen == {"path": "/api/chat", "model": "qwen3:4b"}


def test_ollama_failure_is_status(monkeypatch):
    monkeypatch.setattr(w, "_ollama", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    out = w.run_job(task("h1"))
    assert out["status"].startswith("error")


def test_rackpc_caller_is_confined():
    spec = ca.CALLERS["rackpc"]
    assert spec.session_prefix == "rackpc:" and "admin" not in spec.scopes and "approve" not in spec.scopes
    ok = ca.prefixed_route_allowed
    assert ok("GET", "/v1/agent-messages", "rackpc") and ok("POST", "/v1/agent-messages", "rackpc")
    assert ok("GET", "/v1/agent-threads/{thread}", "rackpc")
    assert not ok("POST", "/v1/agent-goals", "rackpc")
    assert not ok("POST", "/v1/sessions/{id}/turns", "rackpc")
    assert not ok("GET", "/v1/sessions/{id}", "rackpc")
    assert not ok("GET", "/v1/activity", "rackpc")
    assert ok("POST", "/v1/agent-goals", "ares")  # other callers unchanged
