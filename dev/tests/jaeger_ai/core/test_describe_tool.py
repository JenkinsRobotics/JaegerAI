"""``describe_tool`` — richer registry introspection.

After the registry-metadata pass, ``describe_tool`` returns the
tool's permission tier, side-effect class, availability boolean,
required env vars, result budget, examples, and the toolset it
belongs to — not just the schema.

This file pins the new payload shape so a regression that drops
one of these fields gets caught before it ships.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from jaeger_os.core.tools.tool_registry import (
    has_tool, register_tool_instance,
)
from jaeger_os.core.tools.tool_schema import ToolDef
from jaeger_ai.agent.tools.meta import describe_tool


class _Args(BaseModel):
    x: int = 0


@pytest.fixture(autouse=True)
def _ensure_probe_tool():
    """Register a richly-annotated probe tool ONCE, then leave it
    in the registry (the registry tolerates re-registration of the
    same name)."""
    if not has_tool("_describe_probe"):
        register_tool_instance(ToolDef(
            name="_describe_probe",
            description="probe used by describe_tool tests",
            args_model=_Args,
            fn=lambda x=0: {"x": x},
            toolset="diagnostics",
            permission_tier="READ_ONLY",
            side_effect="read",
            max_result_chars=2048,
            requires_env=(),
            examples=('_describe_probe(x=1)',),
        ))


def test_describe_tool_unknown_name_returns_ok_false():
    out = describe_tool(name="totally_not_a_tool_name_xyz")
    assert out["ok"] is False
    assert "unknown" in out["error"].lower()


def test_describe_tool_empty_name_returns_ok_false():
    out = describe_tool(name="")
    assert out["ok"] is False


def test_describe_tool_returns_schema_basics():
    """The base schema fields (name / description / parameters) must
    still come back — callers that only look at those keep working."""
    out = describe_tool(name="_describe_probe")
    assert out["ok"] is True
    assert out["name"] == "_describe_probe"
    assert "probe" in out["description"].lower()
    assert isinstance(out["parameters"], dict)


def test_describe_tool_surfaces_toolset():
    """The new ``toolset`` field tells the model which load_tools
    call would bring in the tool's siblings."""
    out = describe_tool(name="_describe_probe")
    assert out["toolset"] == "diagnostics"


def test_describe_tool_surfaces_permission_tier_and_side_effect():
    """Tier + side-effect surface so the model can reason about
    "will this need user confirmation?" without trying the call."""
    out = describe_tool(name="_describe_probe")
    assert out["permission_tier"] == "READ_ONLY"
    assert out["side_effect"] == "read"


def test_describe_tool_surfaces_availability():
    """``available`` is True when the tool's runtime preconditions
    are met. Our probe has no constraints → always available."""
    out = describe_tool(name="_describe_probe")
    assert out["available"] is True
    assert out["requires_env"] == []


def test_describe_tool_surfaces_max_result_chars():
    out = describe_tool(name="_describe_probe")
    assert out["max_result_chars"] == 2048


def test_describe_tool_surfaces_examples():
    out = describe_tool(name="_describe_probe")
    assert out["examples"] == ["_describe_probe(x=1)"]


def test_describe_tool_legacy_tool_without_metadata_still_describes():
    """A pre-metadata tool (no toolset / tier / examples set) must
    still describe cleanly — falling back to ``(unclassified)`` /
    ``READ_ONLY`` defaults instead of raising."""
    if not has_tool("_legacy_probe"):
        register_tool_instance(ToolDef(
            name="_legacy_probe",
            description="pre-metadata probe",
            args_model=_Args,
            fn=lambda x=0: x,
        ))
    out = describe_tool(name="_legacy_probe")
    assert out["ok"] is True
    # Default fallbacks — no exception, sensible values.
    assert out["toolset"] in ("(unclassified)", "")
    assert out["available"] is True
    assert out["examples"] == []
