"""clients/python/jros_client.py — the copy-me single-file client.

Pins it to the same protocol_v1_fixtures.json that pins the in-repo
Python builders and the Swift decoder, so the vendored file cannot
drift from the wire contract. Also proves it is genuinely standalone
(stdlib only, no jaeger_os import) and that a full turn works against
a scripted fake bridge.

0.9 step 4 split: ``jaeger_os/contract/`` no longer lives in THIS repo
(it's JaegerOS's, a pinned dependency) — the fixtures file is read off
the INSTALLED ``jaeger_os`` package instead of a monorepo-relative
``REPO / "jaeger_os" / ...`` path, which stopped existing the moment
the split moved contract/ to its own repo.
"""

import importlib.util
import json
import sys
from pathlib import Path

import jaeger_os

REPO = Path(__file__).resolve().parents[4]
CLIENT_FILE = REPO / "clients" / "python" / "jros_client.py"
FIXTURES = json.loads(
    (Path(jaeger_os.__file__).resolve().parent
     / "contract" / "protocol_v1_fixtures.json")
    .read_text())


def _load():
    spec = importlib.util.spec_from_file_location("jros_client", CLIENT_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_standalone_no_jaeger_os_import():
    text = CLIENT_FILE.read_text()
    assert "import jaeger_os" not in text
    assert "from jaeger_os" not in text
    before = {m for m in sys.modules if m.startswith("jaeger_os")}
    _load()
    after = {m for m in sys.modules if m.startswith("jaeger_os")}
    assert before == after


def test_ops_match_fixtures():
    mod = _load()
    ops = FIXTURES["ops"]
    assert mod.send_op(ops["send"]["text"],
                       ops["send"]["session"]) == ops["send"]
    assert mod.respond_op(ops["respond"]["id"],
                          ops["respond"]["answer"]) == ops["respond"]
    assert mod.quit_op() == ops["quit"]


def test_parses_every_fixture_frame():
    mod = _load()
    for name, frame in FIXTURES["frames"].items():
        parsed = mod._parse(json.dumps(frame) + "\n")
        assert parsed == frame, name
    assert mod._parse("not json\n") is None
    assert mod._parse("\n") is None
    assert mod._parse('{"no": "discriminator"}\n') is None


FAKE_BRIDGE = r"""
import json, sys
def out(f): sys.stdout.write(json.dumps(f) + "\n"); sys.stdout.flush()
out({"type": "ready", "proto": "1", "instance": "fake", "model": "m"})
for line in sys.stdin:
    op = json.loads(line)
    if op.get("op") == "quit":
        out({"type": "bye", "reason": "quit"}); break
    if op.get("op") == "send":
        out({"type": "state", "busy": True, "session": op["session"]})
        out({"type": "tool", "name": "t", "phase": "done",
             "elapsed_s": 0.1, "session": op["session"]})
        out({"type": "reply", "text": "echo: " + op["text"],
             "error": None, "session": op["session"]})
"""


def test_full_turn_against_fake_bridge():
    mod = _load()
    events = []
    with mod.JrosClient(command=[sys.executable, "-c", FAKE_BRIDGE]) as jros:
        assert jros.ready == {"instance": "fake", "model": "m"}
        reply = jros.turn("hello", session="s1", on_event=events.append)
        assert reply == {"text": "echo: hello", "error": None}
    assert [e["type"] for e in events] == ["state", "tool"]


def test_missing_install_raises():
    mod = _load()
    try:
        mod.JrosClient(jaeger_home="/nonexistent/nowhere")
        raise AssertionError("expected JrosError")
    except mod.JrosError as exc:
        assert "no JROS install" in str(exc)
