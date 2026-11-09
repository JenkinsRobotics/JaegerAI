import json

from jaeger_ai.features.agent_bridge import rackpc_worker as w

def task():
    return {"id": "h1", "thread": "t1", "to": "rackpc", "kind": "task", "from": "grokbot",
            "body": "say PONG", "created_at": 9e12}


def test_failed_post_retries_next_tick_once(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "WORKDIR", tmp_path)
    monkeypatch.setattr(w, "run_job", lambda m: {"status": "done", "outcome": "done", "body": "PONG", "elapsed_s": 1})
    posted = []
    attempts = []

    def fake_call(tool, args):
        if tool == "receipts":
            return {"messages": [task()], "next_after": None}
        attempts.append(args.copy())
        if len(attempts) == 1:
            raise OSError("tunnel down")
        posted.append(args.copy())
        return {}

    monkeypatch.setattr(w, "call", fake_call)
    state = w.State(tmp_path / "state.json")
    w.tick(state)
    assert (w._outbox_path("h1")).exists()
    assert "h1" in state.data["done"]
    w.tick(w.State(tmp_path / "state.json"))
    w.tick(w.State(tmp_path / "state.json"))
    assert len(posted) == 1
    assert posted[0]["reply_to"] == "h1"
    assert attempts[0] == attempts[1]
    assert not (w._outbox_path("h1")).exists()


def test_nested_exception_text_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "WORKDIR", tmp_path)
    monkeypatch.setattr(w, "call", lambda tool, args: {"messages": [task()], "next_after": None} if tool == "receipts" else {})
    monkeypatch.setattr(w, "run_job", lambda m: (_ for _ in ()).throw(
        ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("actual socket failure")])
    ))
    w.tick(w.State(tmp_path / "state.json"))
    rows = [json.loads(line) for line in (tmp_path / "worker.jsonl").read_text().splitlines()]
    assert any("actual socket failure" in json.dumps(row) for row in rows)
