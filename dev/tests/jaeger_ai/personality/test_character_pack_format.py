"""The portable ``character/v1`` seam shared with Mochi/JaegerAnimation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jaeger_ai.personality import character as characters


def _write(path: Path, text: str) -> Path:
    path.mkdir()
    (path / "card.png").write_bytes(b"card")
    (path / "character.yaml").write_text(text, encoding="utf-8")
    return path


def test_every_bundled_pack_is_a_portable_static_character() -> None:
    packs = sorted(characters.characters_root().glob("*/character.yaml"))
    assert len(packs) == 15
    for manifest in packs:
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        assert doc["schema"] == characters.CHARACTER_SCHEMA
        assert doc["character"] == manifest.parent.name
        assert doc["version"] and doc["author"] and doc["license"]
        assert (manifest.parent / doc["card"]).is_file()
        assert doc["kind"] == "clip_set"
        assert doc["default_asset"] in doc["assets"]
        primary = doc["assets"][doc["default_asset"]]
        assert primary == {
            "file": "card.png", "type": "image", "adapter": "image",
        }
        assert doc["render"]["adapter"] == "image"
        assert (manifest.parent / doc["render"]["asset"]).is_file()
        assert doc["default_expression"] in doc["expressions"]

        loaded = characters.load_character(manifest.parent)
        assert loaded.id == doc["character"]
        assert loaded.version == doc["version"]
        assert loaded.card_path() == manifest.parent / "card.png"
        assert loaded.asset("primary") == manifest.parent / "card.png"


def test_mochi_shaped_typed_assets_load_without_animation_runtime(tmp_path: Path) -> None:
    pack = _write(tmp_path / "portable", """\
schema: character/v1
character: portable
name: Portable
version: 2.3.4
author: Test Artist
license: Apache-2.0
description: A cross-application character.
kind: clip_set
assets:
  primary: {file: card.png, type: image, adapter: image}
default_asset: primary
render: {adapter: image, asset: card.png}
expressions: {idle: {clips: card.png, loop: false}}
default_expression: idle
default_mouth: ""
card: card.png
identity: {role: a test character, voice_tone: calm, voice_id: af_heart}
prompt: {custom_instructions: You are Portable.}
""")
    loaded = characters.load_character(pack)
    assert loaded.id == "portable"
    assert loaded.author == "Test Artist"
    assert loaded.kind == "clip_set"
    assert loaded.render["asset"] == "card.png"
    assert loaded.asset("primary") == pack / "card.png"


def test_legacy_jaeger_id_and_flat_assets_remain_readable(tmp_path: Path) -> None:
    pack = _write(tmp_path / "legacy", """\
schema: character/v1
id: old_name
name: Old Name
assets: {card: card.png, avatar: avatar}
identity: {voice_id: af_heart}
""")
    loaded = characters.load_character(pack)
    assert loaded.id == "old_name"
    assert loaded.version == "0.0.0"
    assert loaded.card_path() == pack / "card.png"


def test_wrong_schema_is_named_and_rejected(tmp_path: Path) -> None:
    pack = _write(tmp_path / "wrong", "schema: character/v9\nname: Wrong\n")
    with pytest.raises(ValueError, match=r"character\.yaml.*character/v1"):
        characters.load_character(pack)


def test_new_character_writer_emits_the_shared_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_card(folder: Path, _name: str) -> str:
        (folder / "card.png").write_bytes(b"card")
        return "card.png"

    monkeypatch.setattr(characters, "generate_card", fake_card)
    loaded = characters.create_character(
        "New Friend", role="a test", custom_instructions="Be precise.",
        root=tmp_path,
    )
    doc = yaml.safe_load((loaded.root / "character.yaml").read_text(encoding="utf-8"))
    assert doc["character"] == loaded.id == "new_friend"
    assert "id" not in doc
    assert doc["assets"]["primary"]["file"] == "card.png"
    assert doc["render"]["asset"] == "card.png"
    assert doc["expressions"]["idle"]["clips"] == "card.png"
    assert loaded.card_path().is_file()


def test_profile_edits_preserve_the_render_half(tmp_path: Path) -> None:
    pack = _write(tmp_path / "editable", """\
schema: character/v1
character: editable
name: Editable
kind: clip_set
assets: {primary: {file: card.png, type: image, adapter: image}}
default_asset: primary
render: {adapter: image, asset: card.png}
expressions: {idle: {clips: card.png}}
default_expression: idle
identity: {role: before}
prompt: {custom_instructions: Before.}
revision: 1.0
""")
    characters.save_character_profile(pack, role="after")
    doc = yaml.safe_load((pack / "character.yaml").read_text(encoding="utf-8"))
    assert doc["identity"]["role"] == "after"
    assert doc["render"] == {"adapter": "image", "asset": "card.png"}
    assert doc["expressions"] == {"idle": {"clips": "card.png"}}
    assert doc["revision"] == 1.1

