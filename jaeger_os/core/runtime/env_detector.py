"""Detect whether Lilith is running on a desktop or inside a JROS robot.

The single source of truth for the cognitive/physical skill split. The
launcher passes the result of :func:`detect_environment` to
:class:`lilith.core.registry.Registry.discover` to decide whether
``physical`` skills should load.

Detection signal (in order):

    1. ``LILITH_ENVIRONMENT`` env var, if set, wins (``desktop`` or ``robot``).
    2. Otherwise, default to ``"desktop"``.

When JROS launches Lilith inside a robot, the JROS bootstrap sets
``LILITH_ENVIRONMENT=robot`` in the child process's environment. There
is no autodetection beyond that — being inside a body should be a
deliberate decision JROS makes, not something Lilith infers.

# PORTABILITY: Layer 1 utility. Returns a string label; consumers never
# import platform / os / sysconfig modules to make their own guess.
"""

from __future__ import annotations

import os
from typing import Literal


Environment = Literal["desktop", "robot"]
"""The two valid environment labels."""

VALID_ENVIRONMENTS: tuple[Environment, ...] = ("desktop", "robot")

ENV_VAR_NAME = "LILITH_ENVIRONMENT"
"""Name of the env var that overrides detection."""

DEFAULT_ENVIRONMENT: Environment = "desktop"
"""Lilith assumes desktop unless told otherwise."""


def detect_environment(env: dict[str, str] | None = None) -> Environment:
    """Return the active environment label.

    Parameters:
        env: Optional process-environment-like mapping for tests. When
            ``None`` (the common case), introspects ``os.environ``.

    Returns:
        ``"desktop"`` or ``"robot"``.

    Raises:
        ValueError: when ``LILITH_ENVIRONMENT`` is set to an unknown value.
            Failing loudly here is intentional — a typo (``"Robot"``,
            ``"laptop"``) silently falling back to ``"desktop"`` would
            be a worst-case bug if we shipped that code into a robot.
    """
    if env is None:
        env = dict(os.environ)
    explicit = env.get(ENV_VAR_NAME)
    if explicit is None:
        return DEFAULT_ENVIRONMENT
    normalized = explicit.strip().lower()
    if normalized not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"{ENV_VAR_NAME}={explicit!r} is not a valid environment. "
            f"Use one of {list(VALID_ENVIRONMENTS)}."
        )
    return normalized  # type: ignore[return-value]


def is_robot(env: dict[str, str] | None = None) -> bool:
    """Convenience predicate. Sugar over :func:`detect_environment`."""
    return detect_environment(env) == "robot"


__all__ = [
    "DEFAULT_ENVIRONMENT",
    "ENV_VAR_NAME",
    "Environment",
    "VALID_ENVIRONMENTS",
    "detect_environment",
    "is_robot",
]
