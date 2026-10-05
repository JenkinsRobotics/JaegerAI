"""WebUI and runtime profile locations.

A scratch or test ``JAEGER_STATE_DIR`` owns these trees. Profile writers must
not fall through to the live ``~/.jaeger`` directory while that override is set.
"""
from __future__ import annotations

import os
from pathlib import Path


def _state_dir() -> Path | None:
    raw = os.environ.get("JAEGER_STATE_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _inside(path: Path, root: Path) -> bool:
    resolved = path.expanduser().resolve()
    return resolved == root or root in resolved.parents


def hermes_profile_root() -> Path:
    """The shared Hermes/WebUI profile tree: ``<state root>/hermes``.

    ``HERMES_HOME`` is deliberately not consulted. For the host WebUI it names the
    *agent* home (``hermes-webui-agent``), a different directory; honouring it here made
    the profile tree and the agent home the same path and linked ``profiles`` to itself.
    The state root already follows ``JAEGER_STATE_DIR`` then ``JAEGER_HOME``.
    """
    from jaeger_ai.core.instance.instance import operator_state_root

    return operator_state_root() / "hermes"


def webui_agent_home() -> Path:
    """Host WebUI agent state (``hermes-webui-agent``)."""
    state = _state_dir()
    explicit = os.environ.get("JAEGER_WEBUI_AGENT_STATE", "").strip()
    if state is not None:
        if explicit and _inside(Path(explicit), state):
            return Path(explicit).expanduser()
        return state / "hermes-webui-agent"
    if explicit:
        return Path(explicit).expanduser()
    from jaeger_ai.core.instance.instance import operator_state_root

    return operator_state_root() / "hermes-webui-agent"
