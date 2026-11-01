"""Focused tests for the opt-in, read-only vault boundary."""

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[3] / "jaeger_ai/features/obsidian/adapter.py"
spec = importlib.util.spec_from_file_location("obsidian_adapter", MODULE)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_disabled_and_missing_vault(monkeypatch, tmp_path):
    monkeypatch.delenv("JAEGER_OBSIDIAN_VAULT", raising=False)
    with pytest.raises(adapter.VaultError):
        adapter.list_notes()
    monkeypatch.setenv("JAEGER_OBSIDIAN_VAULT", str(tmp_path / "missing"))
    with pytest.raises(adapter.VaultError):
        adapter.list_notes()


def test_list_read_search_and_limits(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_OBSIDIAN_VAULT", str(tmp_path))
    (tmp_path / "a.md").write_text("---\ntitle: A\n---\nAlpha body", encoding="utf-8")
    (tmp_path / "b.md").write_text("Beta body", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "hidden.md").write_text("Alpha")
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "c.md").write_text("Alpha again")
    assert adapter.list_notes(1)["notes"] == ["a.md"]
    assert adapter.list_notes()["notes"] == ["a.md", "b.md", "folder/c.md"]
    assert adapter.read_note("a.md") == {"path": "a.md", "front_matter": "title: A", "body": "Alpha body"}
    assert [item["path"] for item in adapter.search_notes("alpha")["results"]] == ["a.md", "folder/c.md"]
    assert len(adapter.search_notes("alpha", 1)["results"]) == 1
    with pytest.raises(adapter.VaultError):
        adapter.search_notes("x" * 201)


def test_escape_symlinks_and_size(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (vault / "link.md").symlink_to(outside)
    (vault / "linked_dir").symlink_to(tmp_path, target_is_directory=True)
    (vault / "large.md").write_bytes(b"x" * (adapter.MAX_FILE_BYTES + 1))
    monkeypatch.setenv("JAEGER_OBSIDIAN_VAULT", str(vault))
    assert "link.md" not in adapter.list_notes()["notes"]
    assert "linked_dir/outside.md" not in adapter.list_notes()["notes"]
    for path in ("../outside.md", "link.md", "linked_dir/outside.md", ".obsidian/x.md", "large.md"):
        with pytest.raises(adapter.VaultError):
            adapter.read_note(path)
    assert adapter.search_notes("secret")["results"] == []
