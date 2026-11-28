"""Tests for canonical avatar/v1 pack discovery & validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_avatar import discover_avatar_packs, inspect_avatar_pack


def test_avatar_v1_pack_discovery_and_path_traversal_rejection(tmp_path: Path) -> None:
    good = tmp_path / "vita"
    good.mkdir()
    (good / "avatar.yaml").write_text(
        "schema: avatar/v1\n"
        "avatar: vita\n"
        "name: Vita\n"
        "version: 1.0.0\n"
        "description: Studio companion pack\n"
        "default_profile: warm\n"
        "default_representation: rig\n"
        "profiles:\n"
        "  warm:\n"
        "    character:\n"
        "      name: Vita\n"
        "representations:\n"
        "  rig:\n"
        "    root: assets\n",
        encoding="utf-8",
    )

    bad_escape = tmp_path / "evil"
    bad_escape.mkdir()
    (bad_escape / "avatar.yaml").write_text(
        "schema: avatar/v1\n"
        "avatar: evil\n"
        "representations:\n"
        "  rig:\n"
        "    root: ../../etc\n",
        encoding="utf-8",
    )

    info = inspect_avatar_pack(good)
    assert info.avatar_id == "vita" and info.name == "Vita"
    assert "warm" in info.profiles and "rig" in info.representations

    with pytest.raises(ValueError, match="escapes pack directory"):
        inspect_avatar_pack(bad_escape)

    packs = discover_avatar_packs([tmp_path])
    assert [p.avatar_id for p in packs] == ["vita"]
