"""NDJSON stdio bridge protocol — the contract the Swift app parses.

The bridge drives the real agent via ``boot_for_tui`` + ``run_for_voice``
(both proven by the Rich TUI); these tests fake those two so we can pin
the *protocol* — frame shapes, ordering, clean stdout — without booting a
multi-GB model.
"""

from __future__ import annotations

import io
import json

import pytest

from jaeger_os.interfaces import bridge


class _FakeBoot:
    def __init__(self):
        self.client = object()
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True


def _run(monkeypatch, stdin_text, *, run_reply=None, boot_exc=None):
    """Drive ``bridge.main`` with faked deps; return parsed stdout frames."""
    boot = _FakeBoot()

    def fake_boot(*, instance_name):
        if boot_exc:
            raise boot_exc
        return boot

    def fake_run(client, text, session_key=None):
        return run_reply or {"text": f"echo:{text}", "error": None}

    monkeypatch.setattr("jaeger_os.main.boot_for_tui", fake_boot, raising=False)
    monkeypatch.setattr("jaeger_os.main.run_for_voice", fake_run, raising=False)
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


def test_ready_then_reply_then_idle(monkeypatch):
    rc, frames, boot = _run(monkeypatch, '{"text":"hi"}\n{"op":"quit"}\n')
    assert rc == 0
    types = [f["type"] for f in frames]
    assert types == ["ready", "state", "reply", "state"]
    assert frames[0]["instance"] == "test-inst"
    assert frames[1] == {"type": "state", "busy": True}
    assert frames[2] == {"type": "reply", "text": "echo:hi", "error": None}
    assert frames[3] == {"type": "state", "busy": False}
    assert boot.cleaned is True  # graceful teardown ran


def test_boot_failure_emits_fatal(monkeypatch):
    rc, frames, _ = _run(monkeypatch, "", boot_exc=RuntimeError("locked"))
    assert rc == 1
    assert frames == [{"type": "fatal", "error": "locked"}]


def test_malformed_and_blank_lines_ignored(monkeypatch):
    rc, frames, _ = _run(monkeypatch, '\nnot json\n{"text":"  "}\n{"op":"quit"}\n')
    # Only ready emitted — blank/garbage/empty-text frames produce no turn.
    assert [f["type"] for f in frames] == ["ready"]
    assert rc == 0


def test_turn_error_is_reported_not_raised(monkeypatch):
    rc, frames, _ = _run(
        monkeypatch, '{"text":"x"}\n{"op":"quit"}\n',
        run_reply={"text": "", "error": "model exploded"},
    )
    reply = next(f for f in frames if f["type"] == "reply")
    assert reply == {"type": "reply", "text": "", "error": "model exploded"}
    assert rc == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
