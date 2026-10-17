"""The tool-less model-only lane (Chat tier, specialists) states its limits.

With ``automation.interaction_tier: chat`` the 2026-10-16 SOTA run on
glm-5.3-flash:cloud sent every request down this lane; the base system prompt
still described Jaeger's tools, so the model wrote tool calls as text that
nothing executed (1/37 PASS, 0 tool calls).
"""

from jaeger_ai.core.gateway.server import NO_TOOLS_LANE_NOTE, no_tools_lane_system_prompt


def test_note_is_appended_to_the_base_prompt():
    out = no_tools_lane_system_prompt("You are Jaeger.")
    assert out.startswith("You are Jaeger.")
    assert out.endswith(NO_TOOLS_LANE_NOTE)
    assert "Do not write tool calls" in out


def test_note_alone_when_there_is_no_base_prompt():
    assert no_tools_lane_system_prompt(None) == NO_TOOLS_LANE_NOTE
    assert no_tools_lane_system_prompt("") == NO_TOOLS_LANE_NOTE


def test_note_is_not_duplicated():
    once = no_tools_lane_system_prompt("base")
    assert no_tools_lane_system_prompt(once) == once


def test_model_only_lane_uses_the_note():
    import inspect
    from jaeger_ai.core.gateway import server

    src = inspect.getsource(server)
    assert "system_prompt=no_tools_lane_system_prompt(system_prompt)" in src
