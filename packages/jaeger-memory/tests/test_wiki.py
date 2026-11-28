"""Tests for private-safe LocalWikiStore (symlink/hardlink/root guards + search)."""

from __future__ import annotations

from pathlib import Path
import pytest

from jaeger_memory import LocalWikiStore, WikiStoreError


def test_local_wiki_write_browse_read_search_and_symlink_safety(tmp_path: Path) -> None:
    wiki = LocalWikiStore(tmp_path / "wiki")
    saved = wiki.write_page(
        section="concepts",
        name="JP01 Gimbal Kinematics",
        content="# JP01 Gimbal Kinematics\nPan/tilt range and privacy park at -85 deg.\n",
    )
    assert saved["path"] == "concepts/jp01-gimbal-kinematics.md"

    pages = wiki.browse()
    assert len(pages) == 1 and pages[0]["section"] == "concepts"

    page = wiki.read_page(saved["path"])
    assert "privacy park at -85 deg" in page["content"]

    hits = wiki.search("privacy park gimbal")
    assert len(hits) == 1 and hits[0]["name"] == "jp01-gimbal-kinematics"

    # Symlink outside wiki root must NEVER be exposed or readable
    secret_file = tmp_path / "secret.md"
    secret_file.write_text("TOP SECRET", encoding="utf-8")
    (wiki.root / "notes" / "escape.md").symlink_to(secret_file)
    assert all(p["name"] != "escape" for p in wiki.browse())
    with pytest.raises(WikiStoreError):
        wiki.read_page("notes/escape.md")

    with pytest.raises(WikiStoreError):
        LocalWikiStore(Path("/etc"))
