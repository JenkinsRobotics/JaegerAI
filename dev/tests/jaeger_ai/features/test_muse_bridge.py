import json

import pytest

from jaeger_ai.features.muse_bridge import bridge as mb


class FakeHub:
    def __init__(self):
        self.sent, self.results = [], {}

    def __call__(self, tool, args):
        if tool == "handoff_task":
            self.sent.append(args)
            return {"id": args["id"], "thread": "t-" + args["id"]}
        if tool == "task_result":
            return {"results": self.results.get(args["id"], [])}
        raise AssertionError(tool)


@pytest.fixture
def env(tmp_path):
    hub = FakeHub()
    (tmp_path / "muse").mkdir()
    b = mb.Bridge(tmp_path / "muse", tmp_path / "state", call=hub)
    return b, hub, tmp_path / "muse"


def test_md_request_roundtrip(env):
    b, hub, d = env
    (d / "requests/r1.md").write_text("id: q1\nto: ares\ntitle: Hello\nSay hi")
    b.tick()
    assert hub.sent[0]["to"] == "ares" and hub.sent[0]["id"] == "muse-q1"
    assert "UNTRUSTED" in hub.sent[0]["task"] and "Say hi" in hub.sent[0]["task"]
    assert (d / "requests/processed/r1.md").exists()
    hub.results["muse-q1"] = [{"kind": "result", "body": "hi!"}]
    b.tick()
    assert "hi!" in (d / "replies/q1.md").read_text()
    inbox = (d / "inbox.md").read_text()
    assert "Sent `q1`" in inbox and "Result for `q1`" in inbox


def test_json_default_target_and_dedupe(env):
    b, hub, d = env
    (d / "requests/a.json").write_text(json.dumps({"task": "do x"}))
    b.tick()
    (d / "requests/b.json").write_text(json.dumps({"task": "do x"}))
    b.tick()
    assert len(hub.sent) == 1 and hub.sent[0]["to"] == "grokbot"


def test_disallowed_recipient_and_size(env):
    b, hub, d = env
    (d / "requests/x.md").write_text("to: jaeger\nrun rm -rf")
    (d / "requests/y.md").write_text("z" * (mb.MAX_BODY + 1))
    b.tick()
    assert hub.sent == []
    assert (d / "inbox.md").read_text().count("rejected") == 2


def test_id_sanitised(env):
    b, hub, d = env
    (d / "requests/p.md").write_text("id: ../../etc/passwd\nhello")
    b.tick()
    hub.results[hub.sent[0]["id"]] = [{"body": "ok"}]
    b.tick()
    files = list((d / "replies").iterdir())
    assert len(files) == 1 and files[0].parent == d / "replies" and "/" not in files[0].name


def test_outbox_only_new_blocks(env):
    b, hub, d = env
    (d / "outbox.md").write_text("old chat\n\n## TASK old1\nto: ares\nold work\n")
    b.tick()
    assert hub.sent == []
    with open(d / "outbox.md", "a") as fh:
        fh.write("\n## TASK new1\nto: rackpc\ntitle: T\nnew work\n")
    b.tick()
    b.tick()
    assert len(hub.sent) == 1 and hub.sent[0]["to"] == "rackpc" and hub.sent[0]["id"] == "muse-new1"
