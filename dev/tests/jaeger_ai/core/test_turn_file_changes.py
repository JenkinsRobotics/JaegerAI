from pathlib import Path

import pytest

from jaeger_ai.core.gateway.file_changes import FileChanges


def test_turn_changes_preserve_dirty_before_image_and_survive_restart(tmp_path):
    root = tmp_path.resolve()
    file = root / "dirty.txt"
    file.write_text("user's uncommitted change\n")
    store = FileChanges(root / "state")
    start = store.begin(file)
    file.write_text("user's uncommitted change\nagent addition\n")
    store.finish("s", "r", start)
    again = FileChanges(root / "state")
    record = again.describe("s", "r")
    assert record["files"][0]["added"] == 1
    assert record["canUndo"]
    assert "before" not in record["files"][0]
    again.undo("s", "r")
    assert file.read_text() == "user's uncommitted change\n"
    assert again.describe("s", "r")["undone"]
    with pytest.raises(ValueError):
        again.undo("s", "r")


def test_external_edits_block_entire_undo(tmp_path):
    root = tmp_path.resolve()
    store = FileChanges(root / "state")
    for name in ("one", "two"):
        file = root / name
        file.write_text("before")
        start = store.begin(file)
        file.write_text("after")
        store.finish("s", "r", start)
    (root / "two").write_text("human edit")
    with pytest.raises(ValueError): store.undo("s", "r")
    assert (root / "one").read_text() == "after"
    assert (root / "two").read_text() == "human edit"


def test_new_file_undo_is_recoverable_and_session_isolated(tmp_path):
    root = tmp_path.resolve()
    store = FileChanges(root / "state")
    file = root / "new.txt"
    start = store.begin(file)
    file.write_text("recover me")
    store.finish("s", "r", start)
    assert not store.describe("other", "r")["files"]
    store.undo("s", "r")
    assert not file.exists()
    assert store.describe("s", "r", contents=True)["files"][0]["after"] == "recover me"


def test_symlink_and_binary_are_not_checkpointed(tmp_path):
    root = tmp_path.resolve()
    store = FileChanges(root / "state")
    file = root / "binary"
    file.write_bytes(b"\0bin")
    link = root / "link"
    link.symlink_to(file)
    with pytest.raises(ValueError): store.begin(link)
    with pytest.raises(ValueError): store.begin(file)


def test_multiple_writes_coalesce_but_intervening_external_edit_conflicts(tmp_path):
    root = tmp_path.resolve()
    store = FileChanges(root / "state")
    file = root / "file"
    file.write_text("base")
    first = store.begin(file)
    file.write_text("agent1")
    store.finish("s", "r", first)
    file.write_text("human")
    second = store.begin(file)
    file.write_text("agent2")
    store.finish("s", "r", second)
    assert len(store.describe("s", "r")["files"]) == 1
    assert not store.describe("s", "r")["canUndo"]
