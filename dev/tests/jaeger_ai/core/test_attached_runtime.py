"""Windowed jaeger attaches to a live bridge instead of taking the instance lock.

These are the tests that need attachment to actually happen, so they take the
``allow_bridge_attach`` fixture. It lifts the suite-wide ``JAEGER_NO_ATTACH``
gate only after pinning ``JAEGER_INSTANCE_DIR`` to a tmp root and proving that
root is not inside a live instance tree — so re-enabling attachment here still
cannot reach the operator's running agent. See ``dev/tests/conftest.py``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from jaeger_ai.core.runtime.attached import try_attach_runtime
from jaeger_ai.core.runtime import bridge_socket as bsock
from jaeger_os.contract import protocol


def _serve_one(path: Path, replies: list[dict], barrier: threading.Barrier) -> None:
    sock = bsock.bind(path)
    try:
        barrier.wait(timeout=2)
        conn, _addr = sock.accept()
        text = conn.makefile("rw", buffering=1, encoding="utf-8", newline="\n")
        text.write(json.dumps(protocol.ready_frame("jarvis", "qwen3.5:397b")) + "\n")
        text.flush()
        for raw in text:
            req = json.loads(raw)
            if req.get("op") == "send":
                text.write(json.dumps(protocol.reply_frame("pong", session=req.get("session") or "")) + "\n")
                text.flush()
            elif req.get("op") == "quit":
                break
            replies.append(req)
    finally:
        bsock.close_quietly(sock)
        path.unlink(missing_ok=True)


def _serve_in_background(root: Path) -> tuple[list[dict], threading.Thread]:
    """Stand up a one-shot bridge under ``root`` and wait until it is bound."""
    replies: list[dict] = []
    barrier = threading.Barrier(2)
    thread = threading.Thread(
        target=_serve_one, args=(root / "run" / "bridge.sock", replies, barrier),
        daemon=True,
    )
    thread.start()
    barrier.wait(timeout=2)
    return replies, thread


def test_try_attach_runtime_proxies_a_turn(monkeypatch, allow_bridge_attach):
    monkeypatch.setenv("JAEGER_INSTANCE_NAME", "jarvis")
    replies, thread = _serve_in_background(allow_bridge_attach)

    runtime = try_attach_runtime(instance_name="jarvis")
    assert runtime is not None
    assert runtime.attached is True
    assert runtime.ready["model"] == "qwen3.5:397b"
    result = runtime.run_turn("ping", session_key="gui")
    assert result["text"] == "pong"
    runtime.close()
    thread.join(timeout=2)
    assert any(item.get("op") == "send" for item in replies)


def test_create_runtime_attaches_instead_of_booting(monkeypatch, allow_bridge_attach):
    _replies, thread = _serve_in_background(allow_bridge_attach)

    from jaeger_ai.core.mind_runtime import create_runtime

    booted = {"called": False}

    def boom(*_a, **_k):
        booted["called"] = True
        raise AssertionError("must not boot a second in-process agent")

    monkeypatch.setattr("jaeger_ai.core.mind_runtime.JaegerAIRuntime", boom)
    runtime = create_runtime(bus=object(), config={"instance_name": "jarvis"})
    assert getattr(runtime, "attached", False) is True
    assert booted["called"] is False
    runtime.close()
    thread.join(timeout=2)
