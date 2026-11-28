"""Process-wide thread-safe tool registry (standalone jaeger-tools module)."""

from __future__ import annotations

import inspect
import threading
from functools import wraps
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model

from .tool_schema import ToolDef

_registry: dict[str, ToolDef] = {}
_lock = threading.RLock()


def _synchronized(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return call


class ToolConflict(ValueError):
    """Two owners claimed one tool name without a declared override."""


@_synchronized
def replace_tool_inventory(previous: dict[str, ToolDef], tools: list[ToolDef]) -> None:
    """Atomically replace an owner's inventory after validating every name."""
    proposed = {tool.name: tool for tool in tools}
    if len(proposed) != len(tools):
        raise ToolConflict("Duplicate tool names in proposed inventory")
    for name, tool in previous.items():
        if _registry.get(name) is not tool:
            raise ToolConflict(f"Tool ownership changed during refresh: {name}")
    for name in proposed:
        if name in _registry and name not in previous:
            raise ToolConflict(f"Tool name collides with existing inventory: {name}")
    for name in previous:
        del _registry[name]
    _registry.update(proposed)


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
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        register_tool_instance(
            ToolDef(
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
            ),
            replace=replace,
        )
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
    def _wrap(target: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or target.__name__
        tool_desc = description if description is not None else (inspect.getdoc(target) or "")
        args_model = _synthesize_args_model(target, tool_name)
        register_tool_instance(
            ToolDef(
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
            ),
            replace=replace,
        )
        return target

    if fn is not None and callable(fn):
        return _wrap(fn)
    return _wrap


def _synthesize_args_model(
    fn: Callable[..., Any],
    tool_name: str,
) -> type[BaseModel]:
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001
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
        __config__=ConfigDict(
            arbitrary_types_allowed=True,
            extra="allow"
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            else "forbid",
        ),
        **fields,
    )


def _owner(tool_def: ToolDef) -> str:
    fn = tool_def.fn
    return f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', repr(fn))}"


@_synchronized
def register_tool_instance(tool_def: ToolDef, *, replace: bool = False) -> None:
    existing = _registry.get(tool_def.name)
    if existing is not None and not replace and _owner(existing) != _owner(tool_def):
        raise ToolConflict(
            f"tool {tool_def.name!r} is already registered by {_owner(existing)}; "
            f"{_owner(tool_def)} would silently replace it. Rename one, or register "
            "the intended override with replace=True."
        )
    _registry[tool_def.name] = tool_def


@_synchronized
def unregister_tool(name: str) -> None:
    _registry.pop(name, None)


@_synchronized
def get_tool(name: str) -> ToolDef:
    return _registry[name]


@_synchronized
def get_tools() -> list[ToolDef]:
    return list(_registry.values())


@_synchronized
def has_tool(name: str) -> bool:
    return name in _registry


@_synchronized
def clear_registry() -> None:
    _registry.clear()


@_synchronized
def snapshot_registry() -> dict[str, ToolDef]:
    return dict(_registry)


@_synchronized
def restore_registry(snapshot: dict[str, ToolDef]) -> None:
    _registry.clear()
    _registry.update(snapshot)


__all__ = [
    "ToolConflict",
    "clear_registry",
    "get_tool",
    "get_tools",
    "has_tool",
    "register_tool",
    "register_tool_from_function",
    "register_tool_instance",
    "replace_tool_inventory",
    "restore_registry",
    "snapshot_registry",
    "unregister_tool",
]
