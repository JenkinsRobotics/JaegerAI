"""Integration test: when a personality.json exists at
<instance>/, the assembled system prompt carries the
compose_block fragment.  When it doesn't, the prompt stays as
it was — back-compat with operators who haven't authored a
personality yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_os.personality import (
    Expression,
    Personality,
    save_personality,
)


@pytest.fixture
def layout(tmp_path: Path):
    """Build a minimal InstanceLayout-shaped object pointing at
    tmp_path so assemble_prompt has somewhere to look for
    personality.json without touching real instance state."""
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


# ── back-compat: no personality.json ───────────────────────────────

def test_assemble_prompt_works_without_personality_json(
    layout, monkeypatch,
) -> None:
    """When there's no personality.json, the prompt assembles
    cleanly without the compose_block section."""
    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    assert "How I express myself" not in out


# ── personality wired into prompt ──────────────────────────────────

def test_assemble_prompt_includes_compose_block(layout) -> None:
    p = Personality(
        name="Test",
        custom_instructions="Behave like a test.",
        expression=Expression(directness=0.85, sarcasm=0.10),
    )
    save_personality(p, layout.root / "personality.json")

    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    assert "## How I express myself (calibrated)" in out
    assert "directness: very high" in out


# ── broken file doesn't break boot ─────────────────────────────────

def test_broken_personality_json_is_tolerated(layout) -> None:
    """A corrupted personality.json shouldn't crash the boot —
    operator gets the legacy prompt; they can fix the file later."""
    (layout.root / "personality.json").write_text(
        "{ not actually json }"
    )
    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    # Should still assemble without raising; just won't include
    # the personality block.
    assert "How I express myself" not in out
    assert len(out) > 0


# ── subagent mode skips personality ────────────────────────────────

def test_subagent_mode_skips_personality(layout) -> None:
    """Sub-agents get a focused brief; the personality block would
    dilute the task framing.  Matches existing soul.md handling."""
    p = Personality(
        name="Test",
        expression=Expression(directness=0.85),
    )
    save_personality(p, layout.root / "personality.json")

    from jaeger_os.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="subagent",
                          goal="quick task",
                          context="some context")
    # No personality block in the sub-agent's prompt.
    assert "How I express myself" not in out
