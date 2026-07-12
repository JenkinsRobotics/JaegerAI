"""Integration test: WORKERS RUN VANILLA — the assembled system prompt carries
NO character/persona in any mode.

Measured finding (dev/docs/reality/persona_compiler.md): a 4B's execution degrades ~7%
with a character in context, and the "drop persona when executing" boundary rule
does not hold at any persona size. So persona was moved OUT of the worker prompt
entirely — it is applied by the two-pass output filter (re-voicing the final
reply), which lives in the response path, not prompt assembly. The character's
compiled View is still built by ``Character.character_block()`` (tested in
test_persona_compiler.py); it just no longer enters the worker's prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def layout(tmp_path: Path):
    """A minimal InstanceLayout at tmp_path.  A character may be active, but it
    must NOT reach the worker prompt."""
    from jaeger_ai.core.instance.instance import InstanceLayout
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


# ── the worker prompt is vanilla in agent mode ─────────────────────
def test_agent_prompt_has_no_persona(layout) -> None:
    """No character block, no persona boundary — the worker reasons vanilla."""
    from jaeger_ai.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    assert "## My voice —" not in out
    assert "THE PERSONA BOUNDARY" not in out
    # still a real prompt: safety + framework carry through.
    assert "Jaeger OS" in out
    assert len(out) > 0


# ── an active character still does not leak into the worker ────────
def test_active_character_does_not_reach_worker_prompt(layout) -> None:
    from jaeger_ai.personality.character import set_active_character
    set_active_character(layout.root, "eren_yeager")   # directness 0.85
    from jaeger_ai.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="agent")
    assert "## My voice —" not in out
    assert "be blunt and direct" not in out   # its compiled clause is filter-only


# ── sub-agent mode is vanilla too ──────────────────────────────────
def test_subagent_mode_has_no_character(layout) -> None:
    """Sub-agents get a focused brief and zero persona — their preamble is
    their whole identity."""
    from jaeger_ai.agent.prompts.assemble import assemble_prompt
    out = assemble_prompt(layout, mode="subagent",
                          goal="quick task", context="some context")
    assert "## My voice —" not in out
    assert "focused sub-agent" in out
