"""Character library packing: SOUL.md is the live identity; lore/ stays off the prompt."""
from pathlib import Path

from jaeger_ai.personality.character import characters_root, load_character


def test_load_character_prefers_soul_md(tmp_path: Path):
    (tmp_path / "character.yaml").write_text(
        "schema: character/v1\nid: tester\nname: Tester\n"
        "prompt:\n  soul: yaml soul\n  custom_instructions: short\n",
        encoding="utf-8",
    )
    (tmp_path / "SOUL.md").write_text("I am the SOUL.md voice.\n", encoding="utf-8")
    character = load_character(tmp_path)
    assert character.soul == "I am the SOUL.md voice."
    assert "yaml soul" not in character.character_block()
    assert "I am the SOUL.md voice." in character.character_block()


def test_lore_pack_is_not_in_the_live_prompt(tmp_path: Path):
    (tmp_path / "character.yaml").write_text(
        "schema: character/v1\nid: tester\nname: Tester\n"
        "prompt:\n  soul: I am Tester.\n  custom_instructions: Stay brief.\n",
        encoding="utf-8",
    )
    lore = tmp_path / "lore"
    lore.mkdir()
    (lore / "quotes.md").write_text("Secret canon line.\n", encoding="utf-8")
    character = load_character(tmp_path)
    assert "Secret canon line." in character.quotes
    block = character.character_block()
    assert "Secret canon line." not in block
    assert "I am Tester." in block


def test_glados_soul_is_packed_and_lore_stays_off_prompt():
    glados = load_character(characters_root() / "glados")
    assert glados.soul.strip()
    assert "I am GLaDOS" in glados.soul
    assert "Genetic Lifeform and Disk Operating System" not in glados.personality.custom_instructions
    block = glados.character_block()
    assert "I am GLaDOS" in block
    assert "The cake is a lie." not in block
    assert glados.quotes and "The cake is a lie." in glados.quotes


def test_jarvis_soul_md_is_the_live_identity():
    jarvis = load_character(characters_root() / "jarvis")
    assert (characters_root() / "jarvis" / "SOUL.md").is_file()
    assert "I am JARVIS" in jarvis.soul
    assert "I am JARVIS" in jarvis.character_block()


def test_every_wearable_character_has_soul_and_lore_off_prompt():
    root = characters_root()
    wearable = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder / "character.yaml").is_file():
            continue
        character = load_character(folder)
        if character.neutral:
            continue
        wearable.append(character)
        assert (folder / "SOUL.md").is_file(), folder.name
        assert character.soul.strip(), folder.name
        block = character.character_block()
        assert character.soul.splitlines()[0] in block
        if character.backstory and len(character.backstory) > 48:
            assert character.backstory[:48] not in block
        assert "You are " + character.name not in character.personality.custom_instructions
    assert len(wearable) >= 14
