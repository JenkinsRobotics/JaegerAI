from jaeger_ai.features.knowledge_library import KnowledgeLibrary, LibraryError


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


def test_duplicate_collection_is_rejected(tmp_path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.add(str(root))
    try:
        library.add(str(root))
    except LibraryError:
        pass
    else:
        raise AssertionError("duplicate collection was accepted")
    library.close()
