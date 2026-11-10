"""Per-agent discovery state. The registry remains the inventory owner."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

@dataclass
class ToolSelection:
    scoped: bool | None = None
    groups: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)
    inferred: set[str] = field(default_factory=set)
    reasons: dict[str, str] = field(default_factory=dict)
    catalog: tuple[Any, ...] | None = None
    restricted: frozenset[str] | None = None
    grant: frozenset[str] | None = None

_current: ContextVar[ToolSelection | None] = ContextVar("tool_selection", default=None)
_fallback_groups: ContextVar[frozenset[str]] = ContextVar("unbound_tool_groups", default=frozenset())

def current_selection() -> ToolSelection | None:
    return _current.get()

@contextmanager
def selection_scope(selection: ToolSelection):
    token = _current.set(selection)
    try:
        yield selection
    finally:
        _current.reset(token)

def in_agent_selection(fn):
    @wraps(fn)
    def bound(self, *args, **kwargs):
        with selection_scope(self._tool_selection):
            return fn(self, *args, **kwargs)
    return bound

def active_groups() -> set[str]:
    selection = current_selection()
    return set(selection.groups if selection else _fallback_groups.get())

def set_groups(groups: set[str]) -> None:
    selection = current_selection()
    if selection is not None:
        selection.groups = set(groups)
    else:
        _fallback_groups.set(frozenset(groups))

def tool_permitted(name: str) -> bool:
    # Relevance and schema loading never override trust or a host grant.
    from .toolset_scoping import is_untrusted_content, UNTRUSTED_SAFE
    from jaeger_agent.tool_executor import active_tool_allowlist
    if is_untrusted_content() and name not in UNTRUSTED_SAFE:
        return False
    allowed = active_tool_allowlist()
    if allowed is not None and name not in allowed:
        return False
    state = current_selection()
    return state is None or ((state.restricted is None or name in state.restricted)
                             and (state.grant is None or name in state.grant))
