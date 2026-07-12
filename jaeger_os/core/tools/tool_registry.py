"""Process-wide tool registry.

Two registration paths converge into one map:

  • ``@register_tool(...)`` — module-level decorator for built-in tools
    that are defined statically and bound at import time. Mirrors the
    pattern in hermes-agent/tools/registry.py.
  • ``register_tool_instance(tool_def)`` — runtime registration for
    skills (loaded by ``skill_loader.py`` after smoke tests pass) and
    for MCP-discovered tools (registered after the MCP bridge dials
    its servers). This is the path that keeps the dynamic JROS skill
    model working without forcing every skill into a decorator.

The registry is intentionally a flat dict keyed by tool name.
Versioning (``get_time`` overridden by ``get_time_v2``) is the loader's
concern — by the time a ToolDef is registered here, the loader has
already decided which version wins.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model

from jaeger_os.core.tools.tool_schema import ToolDef


_registry: dict[str, ToolDef] = {}


def register_tool(
    name: str,
    description: str,
    args_model: type[BaseModel],
    *,
    interactive: bool = False,
    dangerous: bool = False,
    beta: bool = False,
    side_effect: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: bind ``fn`` as the handler for tool ``name``.

    Usage::

        class MoveJointArgs(BaseModel):
            joint_id: int = Field(ge=0, le=23)
            target_angle_rad: float

        @register_tool(
            name="move_joint",
            description="Move a single joint to a target angle.",
            args_model=MoveJointArgs,
            dangerous=True,
        )
        def move_joint(joint_id: int, target_angle_rad: float) -> dict:
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        register_tool_instance(ToolDef(
            name=name,
            description=description,
            args_model=args_model,
            fn=fn,
            interactive=interactive,
            dangerous=dangerous,
            beta=beta,
            side_effect=side_effect,
        ))
        return fn

    return decorator


def register_tool_from_function(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    interactive: bool = False,
    dangerous: bool = False,
    beta: bool = False,
    side_effect: str = "",
) -> Any:
    """Decorator that registers ``fn`` by introspecting its signature.

    A drop-in replacement for pydantic-ai's ``@agent.tool_plain`` —
    used during the Phase-6 cutover to remove pydantic-ai while
    preserving the 48 inline JROS tool definitions in ``main.py``.

    Usage (no parens, picks up name + docstring)::

        @register_tool_from_function
        def get_time(timezone: str | None = None) -> dict:
            \"\"\"Return the current time.\"\"\"
            return _impl.get_time(timezone=timezone)

    Usage (with overrides)::

        @register_tool_from_function(name="alias", dangerous=True)
        def actual_name(...) -> dict:
            ...

    The synthesized args model uses ``inspect.signature`` + ``get_type_hints``
    so ``from __future__ import annotations`` modules resolve forward
    refs cleanly. Parameters without an annotation fall back to
    ``typing.Any``.
    """
    def _wrap(target: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or target.__name__
        tool_desc = description if description is not None else (
            inspect.getdoc(target) or ""
        )
        args_model = _synthesize_args_model(target, tool_name)
        register_tool_instance(ToolDef(
            name=tool_name,
            description=tool_desc,
            args_model=args_model,
            fn=target,
            interactive=interactive,
            dangerous=dangerous,
            beta=beta,
            side_effect=side_effect,
        ))
        return target

    # Called as a bare decorator: ``@register_tool_from_function``.
    if fn is not None and callable(fn):
        return _wrap(fn)
    # Called with kwargs: ``@register_tool_from_function(name=...)``.
    return _wrap


def _synthesize_args_model(
    fn: Callable[..., Any], tool_name: str,
) -> type[BaseModel]:
    """Build a Pydantic v2 model from ``fn``'s signature. Shared with
    :mod:`jaeger_os.agent.bridge` — kept here as well so the decorator
    has zero migration-bridge dependency once Phase 6.2 lands."""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001 — unresolved forward refs → Any
        hints = {}

    fields: dict[str, Any] = {}
    for param in sig.parameters.values():
        if param.name in ("self", "cls"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        annotation = hints.get(param.name, Any)
        if param.default is inspect.Parameter.empty:
            fields[param.name] = (annotation, ...)
        else:
            fields[param.name] = (annotation, Field(default=param.default))

    return create_model(  # type: ignore[call-overload]
        f"{tool_name.title().replace('_', '')}Args",
        __config__=ConfigDict(arbitrary_types_allowed=True),
        **fields,
    )


def register_tool_instance(tool_def: ToolDef) -> None:
    """Runtime registration path. Used by ``skill_loader.py`` and the
    MCP bridge — anywhere a ToolDef is built outside a module-level
    decorator. Last write wins, mirroring how versioned skills override
    built-ins of the same name."""
    _registry[tool_def.name] = tool_def


def unregister_tool(name: str) -> None:
    """Remove a tool from the registry. Used by tests and by the skill
    loader's hot-reload path. No-op when the tool is not registered."""
    _registry.pop(name, None)


def get_tool(name: str) -> ToolDef:
    """Look up a tool by exact name. Raises ``KeyError`` when not
    registered — the agent loop catches it and turns the error into a
    tool result so the model can self-correct."""
    return _registry[name]


def get_tools() -> list[ToolDef]:
    """Snapshot of every registered tool, in insertion order. The
    snapshot is a fresh list so callers can mutate it (filter by
    toolset, sort, etc.) without affecting the registry."""
    return list(_registry.values())


def has_tool(name: str) -> bool:
    """``True`` when ``name`` is registered. Cheap predicate the agent
    loop uses before dispatching a model-supplied tool name."""
    return name in _registry


def clear_registry() -> None:
    """Drop every registration. Tests use this to keep state from
    leaking between cases; production code should never call it."""
    _registry.clear()


__all__ = [
    "register_tool",
    "register_tool_from_function",
    "register_tool_instance",
    "unregister_tool",
    "get_tool",
    "get_tools",
    "has_tool",
    "clear_registry",
]
