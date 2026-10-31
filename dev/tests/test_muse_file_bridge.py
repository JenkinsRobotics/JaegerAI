import json
import os
import time

import pytest

from jaeger_ai.features.agent_bridge import muse_file_bridge as mb


@pytest.fixture
def env(tmp_path, monkeypatch):
    folder = tmp_path / "muse"; folder.mkdir()
    monkeypatch.setattr(mb, "FOLDER", folder)
    monkeypatch.setattr(mb, "BRIDGE_DIR", tmp_path / "bridge")
    monkeypatch.setattr(mb, "SETTLE_S", 0)
    calls = []

    def fake(tool, args):
        calls.append((tool, args))
        if tool == "handoff_task":
            return {"id": args["id"], "thread": "th-1"}
        return {"results": [{"id": "r1", "from": "ares", "body": "PONG ```x```", "refs": ["/tmp/a"]}]}
    monkeypatch.setattr(mb, "call", fake)
    return folder, calls


def _write(folder, text, mode="a"):
    with open(folder / "outbox.md", mode) as fh:
        fh.write(text)
    os.utime(folder / "outbox.md", (time.time() - 10, time.time() - 10))


def test_parse_tasks_and_plain():
    ts = mb.parse("hello there\n## TASK t1\nto: ARES\ntitle: Ping\nreply PONG\n## TASK\nbody only\n")
    assert [t["to"] for t in ts] == ["grokbot", "ares", "grokbot"]
    assert ts[1]["title"] == "Ping" and ts[1]["body"] == "reply PONG" and ts[1]["ref"] == "t1"
    assert ts[2]["body"] == "body only"


def test_history_skipped_then_task_sent_once_and_result(env):
    folder, calls = env
    _write(folder, "old questions\n", "w")
    st = mb.State(mb.BRIDGE_DIR / "state.json")
    mb.tick(st)
    assert calls == []  # first start skips history
    _write(folder, "## TASK p1\nto: ares\ntitle: Ping\nreply PONG\n")
    mb.tick(st)
    assert calls[0][0] == "handoff_task" and calls[0][1]["to"] == "ares"
    assert "untrusted" in calls[0][1]["task"]
    inbox = (folder / "inbox.md").read_text()
    assert "sent to ares" in inbox and "RESULT for TASK p1" in inbox and "PONG" in inbox
    assert "```x```" not in inbox  # fences neutralised
    mb.tick(st); mb.tick(st)
    assert sum(1 for c in calls if c[0] == "handoff_task") == 1
    assert (folder / "inbox.md").read_text().count("RESULT") == 1
    assert st.data["pending"] == []


def test_invalid_recipient_and_truncation(env):
    folder, calls = env
    _write(folder, "", "w")
    st = mb.State(mb.BRIDGE_DIR / "state.json"); mb.tick(st)
    _write(folder, "## TASK x\nto: ../../etc\nhi\n")
    mb.tick(st)
    assert not any(c[0] == "handoff_task" for c in calls)
    assert "not sent" in (folder / "inbox.md").read_text()
    _write(folder, "", "w")  # truncated: offset resets, nothing resent
    mb.tick(st)
    assert st.data["offset"] == 0


def test_size_cap(env):
    folder, calls = env
    _write(folder, "", "w")
    st = mb.State(mb.BRIDGE_DIR / "state.json"); mb.tick(st)
    _write(folder, "## TASK big\nto: ares\n" + "a" * 100000)
    mb.tick(st)
    assert len(calls[0][1]["task"]) < mb.MAX_BLOCK_BYTES + 100


def test_token_never_logged(env, tmp_path, capsys):
    mb._log("x", a=1)
    assert "token" not in (mb.BRIDGE_DIR / "bridge.jsonl").read_text().lower()
