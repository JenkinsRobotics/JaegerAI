"""The one place JaegerAI is allowed to look at ARES's home directory.

ARES and JaegerAI are separate products with separate state. JaegerAI owns
transcripts, sessions and execution; ARES owns the browser surface and its own
private session store. ``test_source_ownership`` exists to keep that boundary
real, and it is right to: JaegerAI reading ARES's session state would make the
two impossible to version or run independently.

But the boundary is not "never read anything ARES wrote". Two integrations
deliberately cross it, and both read artifacts ARES *publishes* for exactly this
purpose rather than its private state:

  * ``memory/person.md`` — the distilled cross-agent profile, synthesized from
    Claude Code, Hermes, Codex and ARES sessions. Its whole reason to exist is
    to be read by other agents.
  * MCP server declarations — configuration ARES holds so JaegerAI can register
    the same external servers instead of the operator declaring them twice.

Before this module, each caller resolved ``Path.home() / ".ares"`` inline, which
gave two ungoverned crossings and made the ownership guard fail on legitimate
code. A guard that fails on correct code gets ignored, and then it is not
guarding anything. Routing both through here means there is exactly one place to
audit, and the guard can stay strict everywhere else.

Normal runtime code must never read session transcripts, the session store,
the controller port, or ARES's HTTP API. The only exception is the explicit,
operator-triggered ``features.ares_migration`` importer. Its source-root access
is declared here, is read-only, and is covered by migration/retirement tests.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["ares_home", "ares_migration_source", "ares_shared_artifact"]

_ARES_HOME_ENV = "ARES_HOME"
_DEFAULT_DIRNAME = ".ares"

# Paths under the ARES home that JaegerAI may read, relative to it. Anything
# not listed is private state by default — add here only with a reason, and
# only for something ARES publishes deliberately.
_SHARED_ARTIFACTS = {
    "cross_agent_profile": ("memory", "person.md"),
    "profile_config": ("profiles", "default", "config.yaml"),
    "mcp_config": ("config", "mcp.json"),
    "mcp_config_legacy": ("mcp.json",),
}


def ares_home() -> Path:
    """Where ARES keeps its state, honouring ``ARES_HOME``.

    Returns the path whether or not it exists — callers decide what a missing
    ARES install means for them, and most treat it as "no cross-agent context
    available" rather than an error.
    """
    raw = str(os.environ.get(_ARES_HOME_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / _DEFAULT_DIRNAME


def ares_migration_source() -> Path:
    """Return the explicitly governed source root for operator-triggered migration.

    Unlike shared artifacts, this grants no background read access. It is used
    only by the bounded, auditable migration feature after an explicit tool or
    CLI request, and that feature never writes to the returned path.
    """
    return ares_home()


def ares_shared_artifact(name: str) -> Path:
    """Resolve one of the artifacts ARES publishes for other agents.

    Raises ``KeyError`` for anything undeclared, so a new crossing has to be
    added here — and reviewed — rather than appearing inline in a caller.
    """
    try:
        parts = _SHARED_ARTIFACTS[name]
    except KeyError:
        raise KeyError(
            f"{name!r} is not a declared ARES shared artifact. "
            f"Known: {sorted(_SHARED_ARTIFACTS)}. Add it here with a reason "
            "rather than reading ARES's home directly — JaegerAI must not "
            "inspect ARES private session state."
        ) from None
    return ares_home().joinpath(*parts)
