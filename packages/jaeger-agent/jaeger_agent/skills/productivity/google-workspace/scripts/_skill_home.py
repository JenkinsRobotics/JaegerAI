"""Resolve the per-user state directory for standalone skill scripts.

These scripts may run outside the Jaeger process (system Python, a nix
env, CI), so they cannot import :func:`jaeger_agent.workspace.get_layout`
to reach the instance layout. This module gives them the same answer
using only the stdlib.

Resolution order:

  1. ``JAEGER_SKILL_HOME`` — explicit override, always wins.
  2. ``HERMES_HOME`` — legacy. This skill was imported from Hermes and
     stored its Google OAuth token under ``~/.hermes``; honouring the
     variable keeps an operator who already authenticated there signed
     in.
  3. An existing ``~/.hermes/google_token.json`` — the same migration
     case for someone who never set the variable. Only taken when the
     token is actually there, so a fresh install never touches it.
  4. ``~/.jaeger_ai`` — the default. Matches ``OPERATOR_STATE_DIR_NAME``
     in ``jaeger_ai.core.instance.instance``.

When the agent spawns these scripts it rewrites ``HOME`` to the
instance's own ``home/`` jail (see ``subprocess_env_for_instance``), so
the ``~``-relative default lands inside the instance rather than in the
operator's real home.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_DIR_NAME = ".jaeger_ai"
_LEGACY_DIR_NAME = ".hermes"
_TOKEN_NAME = "google_token.json"


def get_skill_home() -> Path:
    """Return the directory this skill keeps its credentials in."""
    override = os.environ.get("JAEGER_SKILL_HOME", "").strip()
    if override:
        return Path(override).expanduser()

    legacy_env = os.environ.get("HERMES_HOME", "").strip()
    if legacy_env:
        return Path(legacy_env).expanduser()

    legacy_dir = Path.home() / _LEGACY_DIR_NAME
    if (legacy_dir / _TOKEN_NAME).exists():
        return legacy_dir

    return Path.home() / STATE_DIR_NAME


def display_skill_home() -> str:
    """Return a ``~/``-shortened form of :func:`get_skill_home`."""
    home = get_skill_home()
    try:
        return "~/" + str(home.relative_to(Path.home()))
    except ValueError:
        return str(home)
