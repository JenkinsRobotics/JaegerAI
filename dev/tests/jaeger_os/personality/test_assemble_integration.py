"""Integration test: the assembled system prompt carries the ACTIVE
CHARACTER's persona (identity + soul + trait compose_block).

Characters are the only persona now — the instance no longer reads
``personality.json`` / ``soul.md``.  An instance with no character
selected plays the default character; selecting one wires its traits.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def layout(tmp_path: Path):
    """A minimal InstanceLayout at tmp_path.  No character selected → the
    default character; tests pick one via ``set_active_character``."""
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=tmp_path)
    layout.identity_path.write_text(
        "name: Test\n"
        "role: testing\n"
        "personality: A neutral test persona.\n"
        "voice_tone: neutral\n"
    )
    layout.config_path.write_text("model:\n  model_path: /tmp/x.gguf\n")
    layout.manifest_path.write_text(
        '{"schema_version": "1.0.0", "instance_name": "t", "created_at": "2026"}'
    )
    return layout


# ── default character drives the persona ───────────────────────────
def test_default_character_persona_in_prompt(layout) -> None:
    """With no character selected, the prompt carries the DEFAULT
    character's persona compose block — no instance personality.json."""
    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    assert "## How I express myself (calibrated)" in out


# ── selecting a character wires ITS traits ─────────────────────────
def test_active_character_persona_in_prompt(layout) -> None:
    from jaeger_os.personality.character import set_active_character
    set_active_character(layout.root, "eren_yeager")   # directness 0.85
    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    assert "## How I express myself (calibrated)" in out
    assert "directness: very high" in out


# ── a broken/missing pick falls back to the default ────────────────
def test_broken_character_falls_back_to_default(layout) -> None:
    """A bogus active character falls back to the default — the prompt
    still assembles with a persona, never crashes."""
    from jaeger_os.personality.character import set_active_character
    set_active_character(layout.root, "does_not_exist")
    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    assert "## How I express myself (calibrated)" in out
    assert len(out) > 0


# ── sub-agent mode skips the persona block ─────────────────────────
def test_subagent_mode_skips_personality(layout) -> None:
    """Sub-agents get a focused brief; the persona block is skipped."""
    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="subagent",
                          goal="quick task", context="some context")
    assert "How I express myself" not in out
