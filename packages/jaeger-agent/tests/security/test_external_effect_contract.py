"""Release-blocking invariants for authoritative external tools."""

from __future__ import annotations


def test_known_authoritative_tools_are_effect_ledger_classified() -> None:
    import jaeger_agent.tools  # noqa: F401 -- populate the process registry
    from jaeger_os.core.tools.tool_registry import get_tool

    authoritative = {
        "browser",
        "batch_move",
        "create_event",
        "media_control",
        "move_mail",
        "open_on_host",
        "remote_terminal",
        "run_shortcut",
        "send_email",
        "sweep_mail",
        "system_control",
        "terminal",
    }

    unclassified = {
        name: get_tool(name).side_effect
        for name in authoritative
        if get_tool(name).side_effect != "external"
    }
    assert unclassified == {}

