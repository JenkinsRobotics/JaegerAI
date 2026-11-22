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
