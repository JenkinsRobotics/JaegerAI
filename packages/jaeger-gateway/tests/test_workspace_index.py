"""Deterministic tests for the FTS5 workspace file index (index_workspace/search_workspace)."""

from __future__ import annotations

import pathlib

from jaeger_gateway.store import GatewayStore


def _make_tree(root: pathlib.Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("def main():\n    print('hello minecraft world')\n")
    (root / "notes.md").write_text("# Notes\nthe rack pc runs the minecraft server on port 25565\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "pkg.js").write_text("var minecraft = 1;\n")


def test_index_directory_and_fts_search(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "proj"
    _make_tree(root)
    store = GatewayStore(tmp_path / "gw.sqlite")

    stats = store.index_directory(str(root))
    assert stats["indexed"] == 2
    # node_modules is pruned at walk level, so it is never counted as skipped.
    assert store.search_indexed_files("should not index") == []

    hits = store.search_indexed_files("minecraft server")
    assert len(hits) == 1
    assert hits[0]["path"].endswith("notes.md")
    assert "minecraft" in hits[0]["excerpt"]

    hits2 = store.search_indexed_files("hello world")
    assert len(hits2) == 1
    assert hits2[0]["path"].endswith("main.py")


def test_index_removes_stale_rows_and_survives_reopen(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "proj"
    _make_tree(root)
    db = tmp_path / "gw.sqlite"
    store = GatewayStore(db)
    store.index_directory(str(root))

    (root / "notes.md").unlink()
    stats = store.index_directory(str(root))
    assert stats["indexed"] == 1
    assert store.search_indexed_files("minecraft server") == []

    reopened = GatewayStore(db)
    hits = reopened.search_indexed_files("hello world")
    assert len(hits) == 1 and hits[0]["path"].endswith("main.py")


def test_search_empty_query_returns_empty(tmp_path: pathlib.Path) -> None:
    store = GatewayStore(tmp_path / "gw.sqlite")
    assert store.search_indexed_files("   ") == []
