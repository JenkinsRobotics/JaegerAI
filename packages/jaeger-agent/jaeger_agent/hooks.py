"""In-process lifecycle hooks: one registry for the whole agent framework.

Two kinds of hook, decided at registration:

* **Blocking** (``pre_tool`` only) runs before the side effect. It may
  ``allow``, ``deny`` (with a reason the model sees) or ``modify`` the tool
  arguments. A blocking hook that raises is treated as ``deny`` (fail closed),
  the same asymmetry as :mod:`jaeger_agent.shell_hooks`. When several blocking
  hooks answer, ``deny`` wins over ``modify`` wins over ``allow``.
* **Observing** (every other point) is called after the fact. It cannot stop
  anything; exceptions are logged and swallowed so a broken observer never
  breaks a turn. ``post_tool`` observers may return a replacement result
  (like Claude Code's ``updatedToolOutput``); ``None`` keeps the original.

Hook points::

    pre_tool(tool, args)                  blocking   -> HookDecision | None
    post_tool(tool, args, result)         observing  -> replacement result | None
    pre_model(context)                    observing
    post_model(context)                   observing  (usage, duration_ms, ok)
    on_approval(event)                    observing  (approval.request / .resolved)
    on_error(event)                       observing  (tool.failed / turn.failed / model failure)
    on_turn_end(event)                    observing  (turn.finish / failed / cancelled / unknown)
    on_turn_start(event)                  observing  (turn.start)
    on_session_start(event)               observing  (session.created)

Every deny/modify (and a post_tool replacement) is reported on the host's
live stream as ``hook.decision`` (jaeger_agent.live), so the interface shows
it as a node under the tool call it changed.

Legacy plugin hooks (``jaeger_ai.plugins``: pre_tool/post_tool/turn_start/
turn_end/session_start) are bridged in as observers, so there is one
dispatch path, not two.

The Gateway feeds ``on_approval``/``on_error``/``on_turn_end`` from its single
event stream (see ``core/gateway/hooks_bridge.py``), so hooks see exactly what
the interface sees, in the same order.
"""
from __future__ import annotations

import fnmatch
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

HOOK_POINTS: tuple[str, ...] = (
    "pre_tool", "post_tool", "pre_model", "post_model",
    "on_approval", "on_error", "on_turn_end", "on_turn_start", "on_session_start",
)
BLOCKING_POINTS: frozenset[str] = frozenset({"pre_tool"})


@dataclass(frozen=True)
class HookDecision:
    action: str = "allow"  # allow | deny | modify
    reason: str = ""
    args: dict[str, Any] | None = None
    hook: str = ""  # which hook(s) decided

    @classmethod
    def allow(cls) -> "HookDecision":
        return cls("allow")

    @classmethod
    def deny(cls, reason: str) -> "HookDecision":
        return cls("deny", reason)

    @classmethod
    def modify(cls, args: dict[str, Any], reason: str = "") -> "HookDecision":
        return cls("modify", reason, dict(args))


@dataclass
class _Hook:
    point: str
    fn: Callable[..., Any]
    name: str
    matcher: str = "*"
    blocking: bool = False


@dataclass
class HookRegistry:
    _hooks: list[_Hook] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def register(self, point: str, fn: Callable[..., Any], *, name: str | None = None,
                 matcher: str = "*") -> Callable[[], None]:
        """Add a hook; returns an ``unregister`` callable. ``matcher`` is an
        fnmatch pattern on the tool name (tool points only)."""
        if point not in HOOK_POINTS:
            raise ValueError(f"unknown hook point {point!r}; expected one of {HOOK_POINTS}")
        hook = _Hook(point, fn, name or getattr(fn, "__name__", "hook"), matcher or "*",
                     point in BLOCKING_POINTS)
        with self._lock:
            self._hooks.append(hook)

        def unregister() -> None:
            with self._lock:
                if hook in self._hooks:
                    self._hooks.remove(hook)
        return unregister

    def hooks(self, point: str, tool: str | None = None) -> list[_Hook]:
        with self._lock:
            return [h for h in self._hooks if h.point == point
                    and (tool is None or fnmatch.fnmatchcase(tool, h.matcher))]

    def clear(self) -> None:
        with self._lock:
            self._hooks.clear()

    # ── blocking ─────────────────────────────────────────────────────
    def pre_tool(self, tool: str, args: dict[str, Any]) -> HookDecision:
        current = dict(args)
        modified = False
        reasons: list[str] = []
        names: list[str] = []
        for hook in self.hooks("pre_tool", tool):
            try:
                answer = hook.fn(tool, dict(current))
            except Exception as exc:  # noqa: BLE001 — cannot answer => deny
                logger.warning("pre_tool hook %s failed; denying %s", hook.name, tool, exc_info=True)
                return _report(tool, HookDecision("deny", f"hook {hook.name} failed: {type(exc).__name__}",
                                                  None, hook.name))
            if answer is None or answer is True:
                continue
            if answer is False:
                return _report(tool, HookDecision("deny", f"denied by hook {hook.name}", None, hook.name))
            if isinstance(answer, HookDecision):
                if answer.action == "deny":
                    return _report(tool, HookDecision("deny", answer.reason or f"denied by hook {hook.name}",
                                                      None, hook.name))
                if answer.action == "modify" and answer.args is not None:
                    current, modified = dict(answer.args), True
                    names.append(hook.name)
                    if answer.reason:
                        reasons.append(answer.reason)
        if modified:
            return _report(tool, HookDecision("modify", "; ".join(reasons), current, ",".join(names)))
        return HookDecision.allow()

    # ── observing ────────────────────────────────────────────────────
    def post_tool(self, tool: str, args: dict[str, Any], result: Any) -> Any:
        for hook in self.hooks("post_tool", tool):
            try:
                replacement = hook.fn(tool, dict(args), result)
            except Exception:  # noqa: BLE001
                logger.warning("post_tool hook %s failed", hook.name, exc_info=True)
                continue
            if replacement is not None:
                result = replacement
                _report(tool, HookDecision("replace", "result replaced", None, hook.name))
        return result

    def fire(self, point: str, payload: dict[str, Any]) -> None:
        if point in BLOCKING_POINTS or point == "post_tool":
            raise ValueError(f"{point} has its own entry point")
        for hook in self.hooks(point):
            try:
                hook.fn(dict(payload))
            except Exception:  # noqa: BLE001
                logger.warning("%s hook %s failed", point, hook.name, exc_info=True)


def _report(tool: str, decision: HookDecision) -> HookDecision:
    """Show a hook's decision on the live stream (no-op without a host).
    Never includes the rewritten arguments — they can hold secrets."""
    from jaeger_agent import live
    live.emit("hook.decision", {"hook": decision.hook or "hook", "action": decision.action,
                                "reason": str(decision.reason or "")[:300], "tool": tool})
    return decision


#: The process-wide registry. Hosts and plugins register here.
registry = HookRegistry()
register = registry.register

__all__ = ["HOOK_POINTS", "BLOCKING_POINTS", "HookDecision", "HookRegistry", "registry", "register"]
