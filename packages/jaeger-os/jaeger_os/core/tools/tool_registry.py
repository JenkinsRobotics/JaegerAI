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

The registry is a flat dict keyed by tool name, and a name has exactly one
owner. Registering a *different* handler under a taken name raises
:class:`ToolConflict` naming both owners — it used to overwrite silently
(last write wins), so two modules could claim one name and the model would
reach whichever imported last. A deliberate override (a versioned skill
replacing a built-in) must say so with ``replace=True``. Re-registering the
same handler (a module reload) is idempotent.
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
    toolset: str = "",
    permission_tier: str = "",
    side_effect: str = "",
    max_result_chars: int = 0,
    check_fn: Callable[[], bool] | None = None,
    requires_env: tuple[str, ...] = (),
    examples: tuple[str, ...] = (),
    replace: bool = False,
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
            toolset=toolset,
            permission_tier=permission_tier,
            side_effect=side_effect,
            max_result_chars=max_result_chars,
            check_fn=check_fn,
            requires_env=requires_env,
            examples=examples,
        ), replace=replace)
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
    toolset: str = "",
    permission_tier: str = "",
    side_effect: str = "",
    max_result_chars: int = 0,
    check_fn: Callable[[], bool] | None = None,
    requires_env: tuple[str, ...] = (),
    examples: tuple[str, ...] = (),
    replace: bool = False,
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
            toolset=toolset,
            permission_tier=permission_tier,
            side_effect=side_effect,
            max_result_chars=max_result_chars,
            check_fn=check_fn,
            requires_env=requires_env,
            examples=examples,
        ), replace=replace)
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
    :mod:`jaeger_agent.bridge` — kept here as well so the decorator
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


class ToolConflict(ValueError):
    """Two owners claimed one tool name without a declared override."""


def _owner(tool_def: ToolDef) -> str:
    fn = tool_def.fn
    return f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', repr(fn))}"


def register_tool_instance(tool_def: ToolDef, *, replace: bool = False) -> None:
    """Runtime registration path. Used by the MCP bridge, hardware
    capabilities and the decorators — anywhere a ToolDef is built.

    Raises :class:`ToolConflict` when ``tool_def.name`` is already owned by a
    different handler and ``replace`` is not set. The same handler again
    (a module reload, a hardware re-registration) replaces quietly."""
    existing = _registry.get(tool_def.name)
    if existing is not None and not replace and _owner(existing) != _owner(tool_def):
        raise ToolConflict(
            f"tool {tool_def.name!r} is already registered by {_owner(existing)}; "
            f"{_owner(tool_def)} would silently replace it. Rename one, or register "
            "the intended override with replace=True."
        )
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


def snapshot_registry() -> dict[str, ToolDef]:
    """Copy of the live map. Tests restore this after ``clear_registry``."""
    return dict(_registry)


def restore_registry(snapshot: dict[str, ToolDef]) -> None:
    """Replace the live map with ``snapshot``. Used by the test suite so
    a case that emptied the registry cannot strand later cases — module
    tools register on import and cannot re-fire from a cached module."""
    _registry.clear()
    _registry.update(snapshot)


__all__ = [
    "ToolConflict",
    "register_tool",
    "register_tool_from_function",
    "register_tool_instance",
    "unregister_tool",
    "get_tool",
    "get_tools",
    "has_tool",
    "clear_registry",
    "snapshot_registry",
    "restore_registry",
]
