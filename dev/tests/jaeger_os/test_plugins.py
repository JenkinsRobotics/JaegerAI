"""Plugin extension API — third-party tools/commands/hooks.

Pin: the PluginContext collects registrations, fire_hook dispatches and
swallows buggy handlers, unknown hook events are rejected, and discovery is
graceful when there are no plugins.
"""

from __future__ import annotations

import pytest

from jaeger_os.plugins import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


def test_context_collects_tools_commands_hooks():
    ctx = registry.context()
    ctx.register_tool("toolA")
    ctx.register_command("/weather", lambda arg: "sunny")
    ctx.register_hook("post_tool", lambda **kw: None)
    assert ctx.tools == ["toolA"]
    assert "weather" in ctx.commands           # leading slash stripped
    assert len(ctx.hooks["post_tool"]) == 1


def test_unknown_hook_event_is_rejected():
    with pytest.raises(ValueError):
        registry.context().register_hook("bogus", lambda: None)


def test_fire_hook_dispatches_and_swallows_buggy_handlers():
    calls: list[str] = []
    registry.context().register_hook(
        "pre_tool", lambda **kw: calls.append(kw.get("name")))
    registry.context().register_hook(
        "pre_tool", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    registry.fire_hook("pre_tool", name="web_search", data={})
    assert calls == ["web_search"]             # good ran; buggy swallowed


def test_discovery_is_graceful_without_plugins():
    assert registry.discover_plugins("nonexistent.group.xyz") == []
