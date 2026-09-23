"""T01: one owner per tool name; overrides are declared, never silent."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from jaeger_os.core.tools import tool_registry as tr
from jaeger_os.core.tools.tool_schema import ToolDef


class _Args(BaseModel):
    pass


def _first():
    return "first"


def _second():
    return "second"


@pytest.fixture(autouse=True)
def _isolated():
    saved = tr.snapshot_registry()
    tr.clear_registry()
    yield
    tr.restore_registry(saved)


def _tool(fn):
    return ToolDef(name="dup", description="d", args_model=_Args, fn=fn)


def test_second_owner_of_a_name_is_an_actionable_conflict():
    tr.register_tool_instance(_tool(_first))
    with pytest.raises(tr.ToolConflict, match="_first.*_second"):
        tr.register_tool_instance(_tool(_second))
    assert tr.get_tool("dup").fn is _first


def test_same_handler_again_is_idempotent():
    tr.register_tool_instance(_tool(_first))
    tr.register_tool_instance(_tool(_first))
    assert tr.get_tool("dup").fn is _first


def test_declared_override_replaces():
    tr.register_tool_instance(_tool(_first))
    tr.register_tool_instance(_tool(_second), replace=True)
    assert tr.get_tool("dup").fn is _second


def test_decorator_path_is_guarded_too():
    tr.register_tool("dup", "d", _Args)(_first)
    with pytest.raises(tr.ToolConflict):
        tr.register_tool("dup", "d", _Args)(_second)


def test_decorators_accept_a_declared_override():
    tr.register_tool_from_function(name="dup")(_first)
    tr.register_tool_from_function(name="dup", replace=True)(_second)
    assert tr.get_tool("dup").fn is _second
