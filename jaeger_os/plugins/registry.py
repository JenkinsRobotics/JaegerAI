"""Plugin extension API — let third parties add tools, slash commands, and
lifecycle hooks without forking JROS.

Today's ``jaeger_os/plugins/*`` are first-party feature *backends* (TTS,
STT, search). This is the general *extension* surface: a plugin is any
installed package exposing a ``jaeger_os.plugins`` entry point whose
``register(ctx)`` adds capabilities through a :class:`PluginContext`.

    # in some_pkg/__init__.py, advertised as an entry point:
    def register(ctx):
        ctx.register_command("weather", lambda arg: ...)
        ctx.register_hook("post_tool", lambda name, args, result: ...)

Hooks compose into the agent loop's existing ``AgentCallbacks`` — see
:func:`fire_hook`. Commands extend the surfaces' slash handler. Tool
registration collects ToolSpecs for the toolset builder to pick up.

Opt-in + local: discovery only runs when called; a plugin runs in-process
(no network), gated by the operator installing it.
"""

from __future__ import annotations

from typing import Any, Callable

# Known lifecycle hook events. Plugins register against these names.
HOOK_EVENTS = ("pre_tool", "post_tool", "turn_start", "turn_end", "session_start")


class PluginContext:
    """Handed to each plugin's ``register(ctx)``. Collects what it adds."""

    def __init__(self) -> None:
        self.tools: list[Any] = []
        self.commands: dict[str, Callable[..., Any]] = {}
        self.hooks: dict[str, list[Callable[..., Any]]] = {}

    def register_tool(self, tool: Any) -> None:
        """Add a tool (a ToolSpec / callable) the agent can use."""
        self.tools.append(tool)

    def register_command(self, name: str, handler: Callable[..., Any]) -> None:
        """Add a ``/name`` slash command (surfaces dispatch to ``handler``)."""
        self.commands[name.lstrip("/")] = handler

    def register_hook(self, event: str, handler: Callable[..., Any]) -> None:
        """Register a lifecycle hook. ``event`` ∈ :data:`HOOK_EVENTS`."""
        if event not in HOOK_EVENTS:
            raise ValueError(f"unknown hook event {event!r}; "
                             f"expected one of {HOOK_EVENTS}")
        self.hooks.setdefault(event, []).append(handler)


# Process-wide merged registry, populated by discover_plugins().
_CONTEXT = PluginContext()


def discover_plugins(group: str = "jaeger_os.plugins") -> list[str]:
    """Load installed plugins (entry-point ``group``), calling each
    ``register(ctx)``. Returns the names loaded; a broken plugin is logged
    and skipped — never fatal. Idempotent enough for a single boot call."""
    loaded: list[str] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # noqa: BLE001
        return loaded
    try:
        eps = entry_points(group=group)
    except TypeError:                       # <3.10 selection API
        eps = entry_points().get(group, [])  # type: ignore[union-attr]
    for ep in eps:
        try:
            register = ep.load()
            register(_CONTEXT)
            loaded.append(ep.name)
        except Exception as exc:  # noqa: BLE001 — one bad plugin can't break boot
            import sys
            print(f"[jaeger-plugins] {ep.name} failed to load: {exc}",
                  file=sys.stderr)
    return loaded


def context() -> PluginContext:
    """The merged plugin context (registered tools/commands/hooks)."""
    return _CONTEXT


def fire_hook(event: str, **kwargs: Any) -> None:
    """Fire every handler registered for ``event``. Exceptions are swallowed
    per handler — a buggy plugin hook never breaks the turn. Called from the
    agent loop's tool callbacks (pre_tool/post_tool) and turn boundaries."""
    for handler in _CONTEXT.hooks.get(event, ()):
        try:
            handler(**kwargs)
        except Exception:  # noqa: BLE001
            pass


def reset_for_tests() -> None:
    """Clear the global registry (tests only)."""
    global _CONTEXT
    _CONTEXT = PluginContext()
