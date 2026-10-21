"""Plugin extension API — let third parties add tools, slash commands, and
lifecycle hooks without forking JaegerAI.

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

import logging
import hashlib
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

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
_LOCK = threading.RLock()
_LOADED: dict[str, dict[str, Any]] = {}
_HOOK_OWNERS: dict[int, str] = {}


def _entries(group: str):
    from importlib.metadata import entry_points
    try:return list(entry_points(group=group))
    except TypeError:return list(entry_points().get(group, []))


def _identity(ep, group):
    dist=getattr(ep,'dist',None)
    package=str(getattr(dist,'name','') or '')
    version=str(getattr(dist,'version','') or '')
    raw='\0'.join((group,ep.name,ep.value,package,version))
    return hashlib.sha256(raw.encode()).hexdigest()[:32],package,version


def catalog(group: str = 'jaeger_ai.plugins') -> dict[str, Any]:
    """Installed metadata only; never import an entry point to inspect it."""
    from jaeger_ai.core.redaction import redact_text
    rows=[]
    with _LOCK:
        installed={}
        for ep in _entries(group):
            identity,package,version=_identity(ep,group)
            installed[identity]=(ep.name,package,version)
        for identity,loaded in _LOADED.items():
            if loaded['group']==group:installed.setdefault(identity,(loaded['name'],loaded['package'],loaded['version']))
        for identity,(name,package,version) in installed.items():
            loaded=_LOADED.get(identity)
            state=loaded['state'] if loaded else 'installed_not_loaded'
            rows.append({'id':identity,'name':redact_text(name)[:200],'package':redact_text(package)[:200],
                'version':redact_text(version)[:100],'state':state,'active_hooks':loaded['active'] if loaded else 0,
                'hook_count':loaded['hook_count'] if loaded else 0,'tool_count':loaded['tool_count'] if loaded else 0,
                'command_count':loaded['command_count'] if loaded else 0,
                'actions':['pause_hooks'] if state=='loaded' and loaded['hook_count'] else ['resume_hooks'] if state=='hooks_paused' else [],
                'provenance':'installed_distribution_metadata_not_publisher_verification'})
    return {'plugins':rows,'scope':'current_process','activation_performed':False}


def control_hooks(identity: str, action: str, expected_state: str):
    """Quiesce managed hook dispatch only. No import, unload, grant or transport stop."""
    with _LOCK:
        row=_LOADED.get(identity)
        if row is None or row['state']!=expected_state:raise ValueError('Plugin state changed; reload catalog')
        if row['active']:raise ValueError('Plugin hook is running; no lifecycle change made')
        target={'pause_hooks':('loaded','hooks_paused'),'resume_hooks':('hooks_paused','loaded')}.get(action)
        if target is None or row['state']!=target[0] or not row['hook_count']:raise ValueError('No supported hook lifecycle action')
        row['state']=target[1]
        return {'id':identity,'state':row['state'],'scope':'managed_hook_dispatch_only','code_unloaded':False,'tools_changed':False,'restart_policy':'existing_discovery_default_unchanged'}


def discover_plugins(group: str = "jaeger_ai.plugins") -> list[str]:
    """Load installed plugins (entry-point ``group``), calling each
    ``register(ctx)``. Returns the names loaded; a broken plugin is logged
    and skipped — never fatal. Idempotent enough for a single boot call."""
    loaded: list[str] = []
    try:
        from importlib.metadata import entry_points
    except ImportError:
        # Narrowed from bare Exception: only an import failure belongs here,
        # and on any supported Python this cannot happen. Logged rather than
        # swallowed so "no plugins loaded" is never indistinguishable from
        # "plugin discovery could not start".
        logger.warning(
            "importlib.metadata unavailable — plugin discovery disabled",
            exc_info=True,
        )
        return loaded
    for ep in _entries(group):
        identity,package,version=_identity(ep,group)
        with _LOCK:
            old=_LOADED.get(identity)
            if old is not None:
                if old['state'] in {'loaded','hooks_paused'}:loaded.append(ep.name)
                continue  # Failed/uncertain registration must never be replayed.
            if any(row['group']==group and row['name']==ep.name for row in _LOADED.values()):
                continue  # Changed distribution must not overlay previously loaded code.
            row={'name':ep.name,'group':group,'package':package,'version':version,'state':'loading','active':0,'hook_count':0,'command_count':0,'tool_count':0}
            _LOADED[identity]=row
        try:
            register = ep.load()
            staged=PluginContext()
            register(staged)
            with _LOCK:
                if set(staged.commands)&set(_CONTEXT.commands):raise ValueError('Plugin command conflicts with existing owner')
                if any(id(handler) in _HOOK_OWNERS for handlers in staged.hooks.values() for handler in handlers):raise ValueError('Plugin hook already belongs to another owner')
                _CONTEXT.tools.extend(staged.tools);_CONTEXT.commands.update(staged.commands)
                for event,handlers in staged.hooks.items():
                    _CONTEXT.hooks.setdefault(event,[]).extend(handlers)
                    for handler in handlers:_HOOK_OWNERS[id(handler)]=identity
                row.update(state='loaded',hook_count=sum(map(len,staged.hooks.values())),command_count=len(staged.commands),tool_count=len(staged.tools))
            loaded.append(ep.name)
        except Exception as exc:  # noqa: BLE001 — one bad plugin can't break boot
            with _LOCK:row['state']='registration_outcome_unknown'
            # Stays broad on purpose: third-party `register()` can raise
            # anything, and one bad plugin must not stop the others or the
            # boot. Now carries a traceback — a bare message told the
            # operator a plugin failed but never where.
            logger.warning(
                "plugin %s failed to load: %s", ep.name, exc, exc_info=True,
            )
    return loaded


def context() -> PluginContext:
    """The merged plugin context (registered tools/commands/hooks)."""
    return _CONTEXT


def fire_hook(event: str, **kwargs: Any) -> None:
    """Fire every handler registered for ``event``. Exceptions are swallowed
    per handler — a buggy plugin hook never breaks the turn. Called from the
    agent loop's tool callbacks (pre_tool/post_tool) and turn boundaries."""
    with _LOCK:handlers=list(_CONTEXT.hooks.get(event, ()))
    for handler in handlers:
        with _LOCK:
            owner=_LOADED.get(_HOOK_OWNERS.get(id(handler)))
            if owner is not None:
                if owner['state']!='loaded':continue
                owner['active']+=1
        try:
            handler(**kwargs)
        except Exception:  # noqa: BLE001 — a hook must not break the turn
            # Was `pass`: a plugin hook could fail on every single turn and
            # leave no trace anywhere. Still non-fatal, now audible.
            logger.warning(
                "plugin hook for %r raised; continuing", event, exc_info=True,
            )
        finally:
            if owner is not None:
                with _LOCK:owner['active']-=1


def reset_for_tests() -> None:
    """Clear the global registry (tests only)."""
    global _CONTEXT
    _CONTEXT = PluginContext()
    _LOADED.clear();_HOOK_OWNERS.clear()
