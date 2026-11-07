import json
from jaeger_ai.features.agent_bridge import ares_worker as w


def _setup(tmp_path, monkeypatch, msgs):
    monkeypatch.setattr(w, "WORKSPACE", tmp_path)
    monkeypatch.setattr(w, "WORKER_DIR", tmp_path / ".worker")
    posted = []

    def fake_call(tool, args):
        if tool == "receipts":
            return {"messages": msgs if args["after"] == 0 else [], "next_after": None}
        posted.append((tool, args))
        return {}
    monkeypatch.setattr(w, "call", fake_call)
    return posted


def task(i, **kw):
    return {"id": i, "thread": "t1", "to": "ares", "kind": "task", "from": "grokbot",
            "body": "do it", "created_at": 9e12, **kw}


def test_runs_once_and_posts_result(tmp_path, monkeypatch):
    msgs = [task("h1"), task("h2", kind="status"), task("h3", **{"from": "ares"})]
    posted = _setup(tmp_path, monkeypatch, msgs)
    monkeypatch.setattr(w, "device_ok", lambda: [])
    ran = []
    monkeypatch.setattr(w, "run_job", lambda m: ran.append(m["id"]) or
                        {"status": "done", "body": "ok", "artifacts": ["/a"], "elapsed_s": 1})
    st = w.State(tmp_path / ".worker" / "state.json")
    assert w.tick(st) == 1 and ran == ["h1"]
    tool, args = posted[0]
    assert tool == "post_result" and args["to"] == "grokbot" and args["thread"] == "t1"
    assert args["reply_to"] == "h1" and args["artifacts"] == ["/a"]
    assert w.tick(w.State(tmp_path / ".worker" / "state.json")) == 0  # never twice


def test_busy_device_defers(tmp_path, monkeypatch):
    posted = _setup(tmp_path, monkeypatch, [task("h1")])
    monkeypatch.setattr(w, "device_ok", lambda: ["CPU load 2"])
    monkeypatch.setattr(w, "run_job", lambda m: (_ for _ in ()).throw(AssertionError))
    assert w.tick(w.State(tmp_path / "s.json")) == 0 and posted == []


def test_gate_flag_off(monkeypatch):
    monkeypatch.setattr(w, "RESOURCE_GATE", False)
    assert w.device_ok() == []


def test_strips_api_keys_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "WORKSPACE", tmp_path)
    monkeypatch.setattr(w, "_token", lambda: "synthetic-test-ares-token")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(env=kw["env"], cmd=cmd, timeout=kw["timeout"])
        raise w.subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(w.subprocess, "run", fake_run)
    out = w.run_job(task("h9"))
    assert "OPENAI_API_KEY" not in seen["env"] and seen["timeout"] == w.TIMEOUT_S
    assert "timed out" in out["status"] and "--sandbox" in seen["cmd"]


def test_hub_down_then_up_retries_with_backoff(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "WORKER_DIR", tmp_path / ".worker")
    sleeps, attempts = [], {"n": 0}

    async def flaky(tool, args):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionRefusedError("hub down")
        return {"ok": True}
    monkeypatch.setattr(w, "_call", flaky)
    monkeypatch.setattr(w.time, "sleep", sleeps.append)
    assert w.call("whoami", {}, retries=3) == {"ok": True}
    assert attempts["n"] == 3 and sleeps == [1.0, 2.0]


def test_hung_hub_times_out_never_wedges(tmp_path, monkeypatch):
    import asyncio
    import pytest
    monkeypatch.setattr(w, "WORKER_DIR", tmp_path / ".worker")
    monkeypatch.setattr(w, "HUB_TIMEOUT_S", 0.05)
    monkeypatch.setattr(w.time, "sleep", lambda s: None)

    async def hang(tool, args):
        await asyncio.sleep(60)
    monkeypatch.setattr(w, "_call", hang)
    with pytest.raises(RuntimeError, match="hub unreachable"):
        w.call("receipts", {}, retries=1)


def test_tool_error_not_retried(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(w, "WORKER_DIR", tmp_path / ".worker")
    n = {"c": 0}

    async def bad(tool, args):
        n["c"] += 1
        raise w.HubToolError("denied")
    monkeypatch.setattr(w, "_call", bad)
    with pytest.raises(w.HubToolError):
        w.call("receipts", {}, retries=3)
    assert n["c"] == 1


def test_main_loop_survives_hub_down_then_up(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "WORKSPACE", tmp_path)
    monkeypatch.setattr(w, "WORKER_DIR", tmp_path / ".worker")
    monkeypatch.setattr(w, "POLL_S", 15)
    monkeypatch.setattr(w, "BACKOFF_MAX_S", 120)
    seq = ["down", "down", "down", "up", "stop"]
    sleeps = []

    def fake_tick(state):
        s = seq.pop(0)
        if s == "down":
            raise RuntimeError("hub unreachable")
        if s == "stop":
            raise KeyboardInterrupt
        return 0
    monkeypatch.setattr(w, "tick", fake_tick)
    monkeypatch.setattr(w.time, "sleep", sleeps.append)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        w.main([])
    assert sleeps == [15, 30, 60, 15]
    log = (tmp_path / ".worker" / "worker.jsonl").read_text()
    assert '"hub_recovered"' in log
