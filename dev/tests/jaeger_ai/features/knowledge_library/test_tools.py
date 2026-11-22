from jaeger_ai.features.knowledge_library import KnowledgeLibrary
from jaeger_ai.features.knowledge_library import tools
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


def test_agent_tools_return_existing_id_and_list_status(tmp_path, monkeypatch):
    path = tmp_path / "library.db"
    root = tmp_path / "Documents"
    root.mkdir()
    monkeypatch.setattr(tools, "_library", lambda: KnowledgeLibrary(path))

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        first = tools.library_add(str(root), "Documents")
        second = tools.library_add(str(root), "Documents again")
    listed = tools.library_collections()

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["collection"]["already_exists"] is True
    assert second["collection"]["id"] == first["collection"]["id"]
    assert listed["collections"][0]["id"] == first["collection"]["id"]
    assert listed["collections"][0]["document_count"] == 0


def test_reminders_sync_becomes_durable_searchable_knowledge(tmp_path, monkeypatch):
    from jaeger_agent.tools import native_pim

    path = tmp_path / "library.db"
    monkeypatch.setattr(tools, "_library", lambda: KnowledgeLibrary(path))
    monkeypatch.setattr(native_pim, "run", lambda *args, **kwargs: {
        "ok": True,
        "reminders": [{"id": "rem-1", "title": "Renew passport",
                       "list": "Travel", "due": "2027-01-10T09:00:00-08:00",
                       "completed": False, "notes": "Before Egypt"}],
    })

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        receipt = tools.library_sync_reminders()

    assert receipt["ok"] is True
    assert receipt["inserted"] == 1
    assert tools.library_search("Renew passport")["results"]


def test_mail_sync_pages_reads_and_indexes_messages(tmp_path, monkeypatch):
    from jaeger_agent.tools import email

    path = tmp_path / "library.db"
    monkeypatch.setattr(tools, "_library", lambda: KnowledgeLibrary(path))
    monkeypatch.setattr(email, "list_mail", lambda *args, **kwargs: {
        "ok": True, "messages": [{"id": "42", "subject": "Project update",
                                    "sender": "Alex", "date": "Today"}],
        "next_offset": None,
    })
    monkeypatch.setattr(email, "read_mail", lambda *args, **kwargs: {
        "ok": True, "messages": [{"id": "42", "snippet": "The prototype passed."}],
    })

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        receipt = tools.library_sync_mail("iCloud")

    assert receipt["ok"] is True
    assert receipt["complete"] is True
    assert tools.library_search("prototype passed")["results"]
