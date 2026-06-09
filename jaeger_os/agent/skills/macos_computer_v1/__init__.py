"""macOS-native computer control — capability-ladder dispatch.

Public surface:

  * :func:`register` — the skill entry point. Wires
    ``computer_do`` / ``computer_use`` / ``computer_look`` onto the
    agent's tool registry. The skill loader calls this.

Implementation:

  * :mod:`.engines` — one module per capability tier (applescript,
    browser, ax, vision). Each implements the :class:`Engine`
    protocol; each can be tested in isolation.
  * :mod:`.planner` — step → engine selection + dispatch.
  * :mod:`.macos_computer` — agent-facing tool wrappers.

See ``SKILL.md`` for the design contract.

NB: the skill loader imports this module via
``importlib.util.spec_from_file_location`` WITHOUT establishing a
parent-package context. Relative imports at module top-level fail
with "attempted relative import with no known parent package".
This module deliberately does NO top-level imports — every
reference is deferred inside the function bodies below. Once a
caller invokes ``register()``, Python imports the inner modules
through the normal package path (where relative imports work
because the parent IS established that way).
"""

from __future__ import annotations

from typing import Any


def register(host: Any) -> None:
    """Skill entry point — wire the three model-visible tools onto
    the agent's tool registry. The skill loader calls this once.

    All imports are deferred to keep this module loadable by the
    skill loader's parent-less ``spec_from_file_location`` import
    path. By the time we're called, the agent is fully booted and
    the inner modules import normally via the package path."""
    from jaeger_os.agent.skills.macos_computer_v1.macos_computer import register as _register
    _register(host)


# Direct-call surface for tests and non-skill-loader callers. Same
# deferred-import pattern — call these from regular Python and the
# inner modules resolve normally; the skill loader never reaches
# them since it only looks for ``register``.

def computer_do(goal: Any) -> dict:
    """High-level computer control — see ``macos_computer.computer_do``."""
    from jaeger_os.agent.skills.macos_computer_v1.macos_computer import computer_do as _impl
    return _impl(goal)


def computer_use(action: str, target: str = "", **kwargs: Any) -> dict:
    """Dispatch ONE action — see ``macos_computer.computer_use``."""
    from jaeger_os.agent.skills.macos_computer_v1.macos_computer import computer_use as _impl
    return _impl(action=action, target=target, **kwargs)


def computer_look(app: str = "", include_screenshot: bool = False) -> dict:
    """Read-only screen snapshot — see ``macos_computer.computer_look``."""
    from jaeger_os.agent.skills.macos_computer_v1.macos_computer import computer_look as _impl
    return _impl(app=app, include_screenshot=include_screenshot)


__all__ = ["computer_do", "computer_look", "computer_use", "register"]
