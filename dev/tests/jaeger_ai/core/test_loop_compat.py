"""JaegerAI owns ARES aliases, arg-key cleanup, and cron deliver wrapping."""

from __future__ import annotations

from jaeger_agent.dialects import normalize_tool_name
from jaeger_agent.dialects import _shared

from jaeger_ai.core.runtime import loop_compat


def test_install_adds_ares_tool_aliases():
    loop_compat.install()
    valid = {
        "mcp__ares-native__notes_operations",
        "board_view",
        "execute_code",
    }
    assert normalize_tool_name("notes", valid) == "mcp__ares-native__notes_operations"
    assert normalize_tool_name("apple_notes", valid) == "mcp__ares-native__notes_operations"
    assert normalize_tool_name("todo", valid) == "board_view"
    assert normalize_tool_name("todowrite", valid) == "board_view"
    for alias, target in loop_compat.ARES_TOOL_ALIASES.items():
        assert _shared._TOOL_ALIASES[alias] == target


def test_coerce_args_strips_quoted_keys():
    loop_compat.install()
    cleaned = _shared._coerce_args_dict({'"path"': "/tmp/x", " inner ": 1})
    assert cleaned == {"path": "/tmp/x", "inner": 1}


def test_schedule_prompt_schema_gains_deliver_fields():
    import jaeger_agent.tools.scheduling  # noqa: F401 — register tools

    loop_compat.install()
    from jaeger_os.core.tools.tool_registry import get_tool

    tool = get_tool("schedule_prompt")
    fields = tool.args_model.model_fields
    assert "deliver" in fields
    assert "recipient" in fields
    assert getattr(tool.fn, "_jaeger_ai_deliver_wrap", False)


def test_hermetic_loop_is_not_the_sibling_checkout():
    loop_compat.install()
    assert loop_compat.sibling_checkout_path() is None
