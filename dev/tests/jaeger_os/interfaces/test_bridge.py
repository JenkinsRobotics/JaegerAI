"""NDJSON stdio bridge protocol — the contract the Swift shell parses.

Phase-1 hardened contract (SWIFT_APP_ARCHITECTURE_PLAN.md): FAST READY
(transport usable before the model boots, ``agent_state`` streams the
transition), worker-thread turns, interactive permission ``request`` /
``respond``, and the ``bye`` clean-exit marker. These tests fake
``boot_for_tui`` + ``run_for_voice`` so we pin the *protocol* without
booting a multi-GB model. The frame SHAPES are pinned separately against
``protocol_v1_fixtures.json`` (the cross-language fixtures Swift also
tests against).
"""

from __future__ import annotations

import io
import json
import time

import pytest

from jaeger_os.interfaces import bridge, protocol


class _FakeBoot:
    def __init__(self):
        self.client = object()
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True


def _run(monkeypatch, stdin_text, *, run_reply=None, boot_exc=None,
         boot_delay=0.0, run_fn=None):
    """Drive ``bridge.main`` with faked deps; return parsed stdout frames."""
    boot = _FakeBoot()

    def fake_boot(*, instance_name):
        if boot_delay:
            time.sleep(boot_delay)
        if boot_exc:
            raise boot_exc
        return boot

    def fake_run(client, text, session_key=None):
        return run_reply or {"text": f"echo:{text}", "error": None}

    monkeypatch.setattr("jaeger_os.main.boot_for_tui", fake_boot, raising=False)
    monkeypatch.setattr("jaeger_os.main.run_for_voice", run_fn or fake_run,
                        raising=False)
    monkeypatch.setattr(
        "jaeger_os.core.instance.instance.default_instance_name",
        lambda: "test-inst", raising=False,
    )

    proto = io.StringIO()
    monkeypatch.setattr("sys.stdout", proto)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))

    rc = bridge.main(argv=[])
    frames = [json.loads(ln) for ln in proto.getvalue().splitlines() if ln.strip()]
    return rc, frames, boot


def test_fast_ready_then_agent_state_then_turn(monkeypatch):
    rc, frames, boot = _run(monkeypatch, '{"text":"hi"}\n{"op":"quit"}\n')
    assert rc == 0
    types = [f["type"] for f in frames]
    # FAST READY: transport first, agent streams in behind, bye marks
    # the orderly exit.
    assert types == ["ready", "agent_state", "agent_state",
                     "state", "reply", "state", "bye"]
    ready = frames[0]
    assert ready["instance"] == "test-inst"
    assert ready["proto"] == protocol.PROTOCOL_VERSION
    assert ready["agent"] == "booting"
    assert set(protocol.CAPABILITIES) == set(ready["capabilities"])
    assert frames[1]["state"] == "booting"
    assert frames[2]["state"] == "ready"
    assert frames[4] == {"type": "reply", "text": "echo:hi", "error": None,
                         "session": "desktop-app"}
    assert frames[6]["type"] == "bye"
    assert boot.cleaned is True  # graceful teardown ran


def test_session_key_flows_through(monkeypatch):
    seen = {}

    def run_fn(client, text, session_key=None):
        seen["session"] = session_key
        return {"text": "ok", "error": None}

    _run(monkeypatch,
         '{"op":"send","text":"hi","session":"chat-win-2"}\n{"op":"quit"}\n',
         run_fn=run_fn)
    assert seen["session"] == "chat-win-2"


def test_boot_failure_streams_failed_then_fatal(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '{"op":"quit"}\n',
                         boot_exc=RuntimeError("model file missing"))
    assert rc == 1
    types = [f["type"] for f in frames]
    assert types == ["ready", "agent_state", "agent_state", "fatal", "bye"]
    assert frames[2] == {"type": "agent_state", "state": "failed",
                         "model": None, "character": None, "icon": None,
                         "error": "model file missing"}
    assert frames[3]["kind"] == "boot"


def test_lock_conflict_gets_the_locked_kind(monkeypatch):
    rc, frames, _ = _run(
        monkeypatch, '{"op":"quit"}\n',
        boot_exc=RuntimeError("instance 'x' is locked by pid 4 (still running)."))
    fatal = next(f for f in frames if f["type"] == "fatal")
    assert fatal["kind"] == "locked"
    assert rc == 1


def test_turn_during_failed_boot_reports_error(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '{"text":"hi"}\n{"op":"quit"}\n',
                         boot_exc=RuntimeError("nope"))
    reply = next(f for f in frames if f["type"] == "reply")
    assert reply["error"] == "nope"
    assert reply["text"] == ""


def test_malformed_and_blank_lines_ignored(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '\nnot json\n{"text":"  "}\n{"op":"quit"}\n')
    # No turn frames — blank/garbage/empty-text lines produce nothing.
    assert [f["type"] for f in frames] == ["ready", "agent_state",
                                           "agent_state", "bye"]
    assert rc == 0


def test_turn_error_is_reported_not_raised(monkeypatch):
    rc, frames, _ = _run(
        monkeypatch, '{"text":"x"}\n{"op":"quit"}\n',
        run_reply={"text": "", "error": "model exploded"},
    )
    reply = next(f for f in frames if f["type"] == "reply")
    assert reply == {"type": "reply", "text": "", "error": "model exploded",
                     "session": "desktop-app"}
    assert rc == 0


def test_permission_request_respond_roundtrip(monkeypatch):
    """A tool asking for approval mid-turn emits ``request``; the client's
    ``respond`` op resolves it — allow reaches the tool as True. Proves the
    stdin thread stays free while a turn blocks on the answer."""
    from jaeger_os.core.safety.permissions import current_policy
    original = current_policy().confirmation
    answers = {}

    def run_fn(client, text, session_key=None):
        # Simulate a gated tool consulting the policy mid-turn (this runs
        # on the TURN thread, exactly like the real permission path).
        answers["granted"] = current_policy().confirmation.confirm(
            type("Req", (), {"skill": "files", "operation": "write_file"})())
        return {"text": "done", "error": None}

    # respond arrives AFTER the turn starts.
    stdin = ('{"text":"write it"}\n'
             '{"op":"respond","id":"perm1","answer":"allow"}\n'
             '{"op":"quit"}\n')
    try:
        rc, frames, _ = _run(monkeypatch, stdin, run_fn=run_fn)
    finally:
        current_policy().confirmation = original
    req = next(f for f in frames if f["type"] == "request")
    assert req["kind"] == "approval" and req["id"] == "perm1"
    assert req["options"] == ["allow", "deny"]
    assert answers["granted"] is True
    assert rc == 0


def test_identity_query_roundtrip(monkeypatch):
    """``{"op":"query","what":"identity"}`` answers with a result frame
    carrying character/icon/model — the additive read the Swift shell uses
    to refresh tray/header branding after a character switch. Works even
    with no character configured (all-None payload, ok=True)."""
    stdin = '{"op":"query","what":"identity","id":"r1"}\n{"op":"quit"}\n'
    rc, frames, _ = _run(monkeypatch, stdin)
    result = next(f for f in frames if f["type"] == "result")
    assert result["id"] == "r1"
    assert result["ok"] is True
    assert set(result["data"]) == {"character", "icon", "model"}
    assert rc == 0


def test_fixture_frames_match_builders():
    """The cross-language fixtures ARE what the builders produce — if a
    builder changes shape, this fails here and the Swift decoder test
    fails there, symmetrically."""
    import pathlib
    fx = json.loads(
        (pathlib.Path(bridge.__file__).parent / "protocol_v1_fixtures.json")
        .read_text())
    frames = fx["frames"]
    assert fx["proto"] == protocol.PROTOCOL_VERSION
    assert frames["ready"] == protocol.ready_frame(
        "jros-dev", None, agent="booting")
    assert frames["ready_warm"] == protocol.ready_frame(
        "jros-dev", "gemma-4-E4B-it-Q4_K_M.gguf", "Jarvis",
        "/tmp/jarvis.png", agent="ready")
    assert frames["agent_state_booting"] == protocol.agent_state_frame("booting")
    assert frames["agent_state_ready"] == protocol.agent_state_frame(
        "ready", model="gemma-4-E4B-it-Q4_K_M.gguf",
        character="Jarvis", icon="/tmp/jarvis.png")
    assert frames["agent_state_failed"] == protocol.agent_state_frame(
        "failed", error="model file missing")
    assert frames["state_busy"] == protocol.state_frame(True, "desktop-app")
    assert frames["state_idle"] == protocol.state_frame(False, "desktop-app")
    assert frames["tool"] == protocol.tool_frame(
        "web_search", "done", 1.25, "desktop-app")
    assert frames["reply"] == protocol.reply_frame(
        "It's 3:48 PM PDT.", None, "desktop-app")
    assert frames["reply_error"] == protocol.reply_frame(
        "", "model exploded", "desktop-app")
    assert frames["request_approval"] == protocol.request_frame(
        "perm1", "approval", "Allow files.write_file?", ("allow", "deny"))
    assert frames["fatal_boot"] == protocol.fatal_frame("model file missing")
    assert frames["fatal_locked"] == protocol.fatal_frame(
        "instance 'jros-dev' is locked by pid 4242 (still running).",
        kind="locked")
    assert frames["bye"] == protocol.bye_frame()
    assert fx["ops"]["send"] == protocol.send_op("hello", "desktop-app")
    assert fx["ops"]["respond"] == protocol.respond_op("perm1", "allow")
    assert fx["ops"]["quit"] == protocol.quit_op()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
