"""Tool-bundle contract + intersection semantics.

A bundle is a CAP, not a grant: ``bundle ∩ agent_allowlist`` is what the
agent may call. These tests pin the contract module and the intersection
behaviour the Gateway relies on at turn admission.
"""

import pytest
from jaeger_agent.tool_executor import (
    AllowlistToolExecutor,
    active_tool_allowlist,
    tool_allowlist,
)

from jaeger_ai.contract.tool_bundles import TOOL_BUNDLES, bundle_tools, is_known_bundle


def test_every_bundle_is_non_empty_and_known() -> None:
    assert TOOL_BUNDLES, "bundle table must not be empty"
    for name, tools in TOOL_BUNDLES.items():
        assert tools, f"bundle {name!r} must not be empty"
        assert is_known_bundle(name)
        assert bundle_tools(name) == tools


def test_unknown_bundle_fails_closed() -> None:
    assert bundle_tools("robotics.deply") == frozenset()  # typo
    assert not is_known_bundle("robotics.deply")


def test_robotics_deploy_is_never_inside_build() -> None:
    """Deploy must never ride along with build — the whole point of
    fine-grained bundles."""
    assert "robotics_deploy" not in bundle_tools("robotics.build")
    assert "robotics_deploy" in bundle_tools("robotics.deploy")
    assert "robotics_build" in bundle_tools("robotics.build")


class _DenyAllExecutor:
    def execute(self, tool, arguments):  # noqa: ANN001, ANN201
        return {"ok": True}


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_bundle_intersection_caps_inherit_allowlist() -> None:
    """An agent with allowlist=None (inherit) is capped to the bundle."""
    bundle = bundle_tools("robotics.build")
    with tool_allowlist(sorted(bundle)):
        executor = AllowlistToolExecutor(_DenyAllExecutor(), active_tool_allowlist())
        # In-bundle tool is admitted.
        res = executor.execute(_Tool("robotics_build"), {})
        assert res.get("ok") is True
        # Out-of-bundle tool is denied by the runtime executor.
        res = executor.execute(_Tool("robotics_deploy"), {})
        assert res.get("ok") is False
        assert res.get("error_type") == "permission_denied"


def test_bundle_intersection_respects_explicit_agent_list() -> None:
    """An agent with an explicit allowlist is capped to bundle ∩ list."""
    bundle = bundle_tools("robotics.build")
    # Agent explicitly granted only nas_backup; bundle allows more.
    with tool_allowlist(["nas_backup"]):
        executor = AllowlistToolExecutor(_DenyAllExecutor(), active_tool_allowlist())
        assert executor.execute(_Tool("nas_backup"), {}).get("ok") is True
        # robotics_build is in the bundle but not the agent's explicit list.
        assert executor.execute(_Tool("robotics_build"), {}).get("ok") is False


def test_character_agent_stays_at_zero_inside_any_bundle() -> None:
    """CHARACTER role default is [] (enforced no-tools) — a goal bundle
    must never widen it."""
    with tool_allowlist([]):
        executor = AllowlistToolExecutor(_DenyAllExecutor(), active_tool_allowlist())
        for tool_name in bundle_tools("goals"):
            res = executor.execute(_Tool(tool_name), {})
            assert res.get("ok") is False, f"{tool_name} must be denied for CHARACTER"
            assert res.get("error_type") == "permission_denied"
