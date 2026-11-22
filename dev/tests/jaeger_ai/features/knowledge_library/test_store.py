from jaeger_ai.features.knowledge_library import KnowledgeLibrary
from jaeger_ai.features.knowledge_library import store


def test_collection_index_search_read_and_symlink_escape(tmp_path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "design.md").write_text("hub and spoke orchestrator", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("must not index", encoding="utf-8")
    (root / "escape.txt").symlink_to(outside)
    library = KnowledgeLibrary(tmp_path / "library.db")
    collection = library.add(str(root))

    report = library.index(collection["id"])
    assert report["indexed"] == 1
    results = library.search("orchestrator")
    assert len(results) == 1
    assert library.read(results[0]["id"])["content"] == "hub and spoke orchestrator"
    assert library.search("must not index") == []
    library.close()


def test_duplicate_collection_returns_existing_identity(tmp_path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    library = KnowledgeLibrary(tmp_path / "library.db")
    created = library.add(str(root))
    duplicate = library.add(str(root), "A label that must not replace the original")
    assert created["already_exists"] is False
    assert duplicate["already_exists"] is True
    assert duplicate["id"] == created["id"]
    assert duplicate["root"] == created["root"]
    library.close()


def test_collection_list_includes_index_status(tmp_path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "one.md").write_text("one", encoding="utf-8")
    library = KnowledgeLibrary(tmp_path / "library.db")
    collection = library.add(str(root))
    assert library.list()[0]["document_count"] == 0
    library.index(collection["id"])
    listed = library.list()[0]
    assert listed["id"] == collection["id"]
    assert listed["document_count"] == 1
    assert listed["last_indexed_at"] is not None
    library.close()


def test_index_prunes_dependency_trees(tmp_path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "real.md").write_text("keep me", encoding="utf-8")
    dependency = root / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (dependency / "noise.md").write_text("do not index", encoding="utf-8")
    library = KnowledgeLibrary(tmp_path / "library.db")
    collection = library.add(str(root))

    report = library.index(collection["id"])

    assert report["indexed"] == 1
    assert report["pruned_directories"] == 1
    assert library.search("keep me")
    assert library.search("do not index") == []
    library.close()


def test_truncated_rescan_never_deletes_unvisited_documents(tmp_path, monkeypatch) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "a.md").write_text("alpha", encoding="utf-8")
    (root / "b.md").write_text("bravo", encoding="utf-8")
    library = KnowledgeLibrary(tmp_path / "library.db")
    collection = library.add(str(root))
    library.index(collection["id"])
    monkeypatch.setattr(store, "MAX_FILES", 1)

    report = library.index(collection["id"])

    assert report["truncated"] is True
    assert report["removed"] == 0
    assert library.search("alpha")
    assert library.search("bravo")
    library.close()
