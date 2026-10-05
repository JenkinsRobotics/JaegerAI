"""Attached slash turns run through the real worker path without NameError.

``_execute_attached_turn``'s slash branch once carried a pasted model-turn
loop that read ``turn_id``, ``out`` and ``reply`` — names that exist only in
``_execute_native_turn``. Every attached ``/command`` therefore raised
``NameError`` (hidden by ``# noqa: F821``) and surfaced as an error frame
("name 'reply' is not defined").
"""
import io
import json
import queue
import threading

from jaeger_ai.interfaces import bridge


def _run_through_worker(request: dict) -> list[dict]:
    """Queue one request exactly as the attach socket does and drain the worker.

    The attach reader enqueues ``(req, writer)`` for ``op == "turn"`` with a
    cancel event and a completion callback; ``_turn_worker`` then dispatches it
    through ``_execute_turn`` into ``_execute_attached_turn``.
    """
    ctx = bridge._Ctx()
    out = io.StringIO()
    completed = threading.Event()
    req = {
        "op": "turn",
        "_cancel_event": threading.Event(),
        "_on_complete": completed.set,
        **request,
    }
    turns: "queue.Queue" = queue.Queue()
    turns.put((req, out))
    turns.put(None)
    worker = threading.Thread(target=bridge._turn_worker, args=(out, ctx, turns))
    worker.start()
    worker.join(timeout=20)
    assert not worker.is_alive(), "turn worker did not finish"
    assert completed.is_set(), "attached turn never signalled completion"
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _replies(frames: list[dict]) -> list[dict]:
    return [f for f in frames if f.get("type") == "reply"]


def test_attached_slash_replies_through_worker_without_nameerror():
    frames = _run_through_worker({"text": "/help", "session": "slash-s1", "id": 41})
    replies = _replies(frames)
    assert len(replies) == 1, frames
    reply = replies[0]
    assert not reply.get("error"), reply
    assert reply["id"] == 41
    assert reply["text"].strip()


def test_attached_slash_brackets_reply_with_busy_then_idle_state():
    frames = _run_through_worker({"text": "/help", "session": "slash-s2"})
    states = [f["busy"] for f in frames if f.get("type") == "state"]
    assert states == [True, False], frames
    assert not any(f.get("error") for f in _replies(frames)), frames


def test_attached_slash_unknown_command_is_a_reply_not_a_crash():
    frames = _run_through_worker({"text": "/no-such-command", "session": "slash-s3", "id": 5})
    replies = _replies(frames)
    assert len(replies) == 1, frames
    assert not replies[0].get("error"), replies[0]
    assert replies[0]["id"] == 5
