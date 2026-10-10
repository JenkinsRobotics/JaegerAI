"""Junk sessions are archived (never deleted); real chats, system and agent homes stay."""
import json

from jaeger_ai.core.gateway import session_hygiene as h


def row(sid, title="New Conversation", n=3, **meta):
    return {"session_id": sid, "title": title, "message_count": n, "metadata": meta}


def test_classification():
    cases = {
        "sota-CLAR-03-127832": "junk", "noskip-mem-01-jaeger-5cb": "junk",
        "task:task_28bed9cc6f43e3": "junk", "jaeger-computer-use-live-1": "junk",
        "paste-only": "junk", "cap-mem2a-de4ebd": "junk", "cap-tool-de4ebd": "junk", "desktop-app": "system", "jaeger-initiative": "system",
        "heartbeat": "system", "kanban_idle": "system",
    }
    for sid, kind in cases.items():
        assert h.classify(row(sid))[0] == kind, sid
    assert h.classify(row("1c11871c", "stack-verify-probe"))[0] == "junk"
    assert h.classify(row("c245fc26", "Test Chat"))[0] == "junk"
    assert h.classify(row("x1", "[skill-review:kanban] Improve"))[0] == "junk"
    assert h.classify(row("e1", "New Conversation", n=0))[0] == "junk"
    # Real conversations stay, even untitled ones with messages.
    assert h.classify(row("5bb9b9fe-54ba", "hey who am i do you know"))[0] == "chat"
    assert h.classify(row("a05197e2-0833", "New conversation", n=4))[0] == "chat"
    assert h.classify(row("agent-jaeger", "Jaeger", n=0, agent_id="native:jaeger", home=True))[0] == "agent"


def test_plan_skips_already_archived_and_keeps_chats():
    rows = [row("sota-A"), row("sota-B", archived=True), row("real", "hey")]
    assert [i["session_id"] for i in h.plan(rows)] == ["sota-A"]


def test_apply_archives_through_the_patch_writer_and_restore_undoes_it(tmp_path):
    calls = []
    patch = lambda sid, archived: calls.append((sid, archived)) or 200
    items = h.plan([row("sota-A"), row("noskip-B"), row("real", "hey")])
    manifest = h.apply(items, patch, tmp_path)
    assert calls == [("sota-A", True), ("noskip-B", True)]
    rec = json.loads(manifest.read_text())
    assert rec["results"] == {"sota-A": 200, "noskip-B": 200}
    assert "delete" not in manifest.read_text().lower()
    calls.clear()
    assert h.restore(manifest, patch) == {"sota-A": 200, "noskip-B": 200}
    assert calls == [("sota-A", False), ("noskip-B", False)]


def test_gateway_archives_probe_sessions_at_creation_but_never_a_new_chat(tmp_path):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    probe = h.archive_on_create(store, store.ensure_session("sota-X-1", title="New Conversation"))
    assert probe["metadata"]["archived"] is True and probe["metadata"]["auto_archived"]
    titled = h.archive_on_create(store, store.ensure_session("abc", title="stack-verify-probe"))
    assert titled["metadata"]["archived"] is True
    chat = h.archive_on_create(store, store.ensure_session("def", title="New Conversation"))
    assert not (chat.get("metadata") or {}).get("archived")
    assert store.get_session("sota-X-1") is not None  # archived, not deleted
