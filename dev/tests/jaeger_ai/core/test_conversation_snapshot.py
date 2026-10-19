"""Read-only recovery snapshot contracts, isolated SQLite only."""
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def test_snapshot_pins_partial_receipt_and_cursor_without_admitting_queue(tmp_path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.admit_request("s", "existing question", request_id="r")
    store.enqueue_request("s", "queued follow-up", request_id="q")
    store.append_event("s", "turn.delta", {"request_id": "other", "delta": "WRONG"})
    event = store.append_event("s", "turn.delta", {"request_id": "r", "delta": "Partial"})
    snapshot = store.get_session("s", conversation=True)
    assert snapshot["partial_text"] == "Partial"
    assert snapshot["event_cursor"] == event["event_id"]
    assert snapshot["latest_request"]["request_id"] == "r"
    assert "input_text" not in snapshot["latest_request"]
    assert store.get_request("q")["status"] == "queued"


def test_terminal_final_answer_does_not_duplicate_streamed_text(tmp_path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.admit_request("s", "question", request_id="r")
    store.append_event("s", "turn.delta", {"request_id": "r", "delta": "Partial"})
    store.complete_request("r", status="completed", result={}, assistant_text="Final answer")
    snapshot = store.get_session("s", conversation=True)
    assert snapshot["partial_text"] == ""
    assert snapshot["messages"][-1]["content"] == "Final answer"
    assert snapshot["latest_request"]["status"] == "completed"


def test_unknown_retains_partial_even_after_replay_retention(tmp_path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.admit_request("s", "question", request_id="r")
    store.append_event("s", "turn.delta", {"request_id": "r", "delta": "Keep this"})
    store.complete_request("r", status="execution_unknown", result={})
    with store._get_conn() as conn:
        conn.execute("DELETE FROM events WHERE event='turn.delta'")
    snapshot = store.get_session("s", conversation=True)
    assert snapshot["partial_text"] == "Keep this"
    assert snapshot["latest_request"]["status"] == "execution_unknown"


def test_concurrent_write_cannot_land_between_history_and_cursor(tmp_path, monkeypatch):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.admit_request("s", "question", request_id="r")
    original = store._get_conn
    injected = False

    class Reader:
        def __init__(self):
            self.conn = original()
        def __enter__(self):
            self.conn.__enter__()
            return self
        def __exit__(self, *args):
            return self.conn.__exit__(*args)
        def execute(self, sql, args=()):
            nonlocal injected
            if "SELECT * FROM messages" in sql and not injected:
                injected = True
                # Separate WAL writer after this reader established its snapshot.
                with original() as writer:
                    store.append_message("s", "assistant", "Concurrent answer", conn=writer)
                store.append_event("s", "turn.delta", {"request_id":"r", "delta":"Concurrent answer"})
            return self.conn.execute(sql, args)

    monkeypatch.setattr(store, "_get_conn", Reader)
    before = store.get_session("s", conversation=True)
    assert not any(m["content"] == "Concurrent answer" for m in before["messages"])
    after = store.get_session("s", conversation=True)
    assert any(m["content"] == "Concurrent answer" for m in after["messages"])
    assert after["event_cursor"] > before["event_cursor"]
